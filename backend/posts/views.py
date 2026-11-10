"""B 子系统 HTTP 接口（契约 5.1 / 5.2 / 5.3 / 5.4）。

接口全部挂在 /api/v1 下，成功走 common.responses.ok()，失败由统一异常处理器转错误信封。
"""
import logging
from datetime import datetime

from django.db import IntegrityError, connection, transaction
from django.db.models import Q
from django.db.models import Value
from django.db.models.functions import Collate, StrIndex
from django.http import FileResponse
from django.utils import timezone
from rest_framework import serializers as drf_serializers
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.views import APIView

from common.api import OptionalAuthAPIView, require_demo_mode
from common.contracts import post_summary as shared_post_summary
from common.exceptions import ApiError
from common.responses import ok, page_payload
from common.serializers import PageQuery, parse_query
from integration.auth import current_actor, require_actor, require_campus_verified
from integration.claims import close_pending_claims, has_completed_claim
from posts import services
from posts.imagetype import ALLOWED_MIME, MAX_IMAGE_BYTES, detect_image_mime
from posts.models import Campus, Category, Location, Post, PostImage
from posts.presenters import image_view, post_detail, post_summary, publisher_summaries
from posts.serializers import KEYWORD_MAX, PostCreateSerializer, PostPatchSerializer
from workflow.transitions import transit

logger = logging.getLogger("b.posts")

CREATE_FIELDS = {
    "post_type",
    "title",
    "category_id",
    "description",
    "location_id",
    "location_detail",
    "occurred_at",
    "handover_note",
    "image_ids",
    "request_id",
}
PATCH_FIELDS = {
    "title",
    "category_id",
    "description",
    "location_id",
    "location_detail",
    "occurred_at",
    "image_ids",
}
PUBLIC_STATUSES = (Post.STATUS_OPEN, Post.STATUS_IN_HANDOVER)
LISTABLE_STATUSES = (Post.STATUS_OPEN, Post.STATUS_IN_HANDOVER, Post.STATUS_COMPLETED)
SORT_CHOICES = {"latest", "occurred_latest"}

_DATETIME_FIELD = drf_serializers.DateTimeField()


# ---------------------------------------------------------------- 小工具
def _reject_unknown(data, allowed: set, hint: str = "未知字段或只读字段，不能由客户端提交"):
    if not hasattr(data, "keys"):
        raise ApiError(
            400, "VALIDATION_ERROR", "请检查填写内容", {"non_field_errors": ["请求体必须是 JSON 对象"]}
        )
    unknown = [key for key in data.keys() if key not in allowed]
    if unknown:
        raise ApiError(
            400,
            "VALIDATION_ERROR",
            "请检查填写内容",
            {key: [hint] for key in unknown},
        )


def _parse_datetime(raw: str, field: str) -> datetime:
    try:
        return _DATETIME_FIELD.to_internal_value(raw)
    except Exception:
        raise ApiError(400, "VALIDATION_ERROR", "请检查填写内容", {field: ["时间格式不正确，应为 ISO 8601"]})


def _require_dict_id(model, value: str, field: str):
    if not model.objects.filter(pk=value).exists():
        raise ApiError(400, "VALIDATION_ERROR", "请检查填写内容", {field: ["字典 ID 不存在"]})


def _coerce_image_ids(raw_ids) -> list[int]:
    result = []
    for raw in raw_ids:
        try:
            result.append(int(raw))
        except (TypeError, ValueError):
            raise ApiError(400, "VALIDATION_ERROR", "请检查填写内容", {"image_ids": [f"图片 ID 不合法: {raw}"]})
    return result


def _load_post(pk, *, for_update=False, with_images=True):
    queryset = Post.objects.select_for_update() if for_update else Post.objects.select_related("category", "location__campus")
    if with_images:
        queryset = queryset.prefetch_related("images")
    post = queryset.filter(pk=pk).first()
    if post is None:
        raise ApiError(404, "NOT_FOUND", "信息不存在")
    return post


def _load_owned_post(pk, actor):
    """写操作加载：非本人对已撤回信息返回 404，其余返回 403。"""
    post = _load_post(pk, for_update=True, with_images=False)
    if post.publisher_id != actor.id:
        if post.status == Post.STATUS_WITHDRAWN:
            raise ApiError(404, "NOT_FOUND", "信息不存在")
        raise ApiError(403, "FORBIDDEN", "只能操作本人发布的信息")
    return post


def _bind_images(post: Post, raw_ids, actor, *, replace=False) -> None:
    """把图片按数组顺序绑定到信息上；必须与信息保存处于同一事务。"""
    ids = _coerce_image_ids(raw_ids or [])
    if not ids and not replace:
        return
    if len(set(ids)) != len(ids):
        raise ApiError(400, "VALIDATION_ERROR", "请检查填写内容", {"image_ids": ["图片 ID 不能重复"]})
    if len(ids) > 6:
        raise ApiError(400, "VALIDATION_ERROR", "请检查填写内容", {"image_ids": ["每条信息最多 6 张图片"]})

    selected = Q(id__in=ids)
    if replace:
        selected |= Q(post_id=post.id)
    rows = PostImage.objects.select_for_update().filter(selected).order_by("id")
    images = {image.id: image for image in rows}
    if replace:
        post.images.exclude(id__in=ids).update(post=None, sort_order=0)
    for index, image_id in enumerate(ids):
        image = images.get(image_id)
        if image is None:
            raise ApiError(400, "VALIDATION_ERROR", "请检查填写内容", {"image_ids": [f"图片 {image_id} 不存在"]})
        if image.owner_id != actor.id:
            raise ApiError(403, "FORBIDDEN", "只能绑定本人上传的图片")
        if image.post_id is not None and image.post_id != post.id:
            raise ApiError(
                400, "VALIDATION_ERROR", "请检查填写内容", {"image_ids": ["图片已绑定其他信息"]}
            )
        image.post = post
        image.sort_order = index
        image.save(update_fields=["post", "sort_order"])


# ---------------------------------------------------------------- POST /posts, GET /posts
class PostCollectionView(APIView):
    def get(self, request):
        params = request.query_params
        queryset = (
            Post.objects.select_related("category", "location__campus")
            .prefetch_related("images")
            .order_by("-created_at", "-id")
        )

        status_param = params.get("status")
        if status_param:
            if status_param not in LISTABLE_STATUSES:
                raise ApiError(
                    400,
                    "VALIDATION_ERROR",
                    "请检查填写内容",
                    {"status": ["状态只能是 open、in_handover 或 completed"]},
                )
            queryset = queryset.filter(status=status_param)
        else:
            # 默认只展示进行中与交接中；已撤回无论如何都不出现
            queryset = queryset.filter(status__in=PUBLIC_STATUSES)

        post_type = params.get("post_type")
        if post_type:
            if post_type not in ("lost", "found"):
                raise ApiError(
                    400,
                    "VALIDATION_ERROR",
                    "请检查填写内容",
                    {"post_type": ["类型只能是 lost 或 found"]},
                )
            queryset = queryset.filter(post_type=post_type)

        keyword = params.get("keyword")
        if keyword is not None:
            keyword = keyword.strip()
            if len(keyword) > KEYWORD_MAX:
                raise ApiError(
                    400,
                    "VALIDATION_ERROR",
                    "请检查填写内容",
                    {"keyword": [f"关键词最多 {KEYWORD_MAX} 字"]},
                )
            if keyword:
                # INSTR treats % and _ literally. MySQL's default collation folds case.
                title = Collate("title", "utf8mb4_bin") if connection.vendor == "mysql" else "title"
                description = Collate("description", "utf8mb4_bin") if connection.vendor == "mysql" else "description"
                queryset = queryset.alias(
                    title_match=StrIndex(title, Value(keyword)),
                    description_match=StrIndex(description, Value(keyword)),
                ).filter(Q(title_match__gt=0) | Q(description_match__gt=0))

        category_id = params.get("category_id")
        if category_id:
            _require_dict_id(Category, category_id, "category_id")
            queryset = queryset.filter(category_id=category_id)

        campus_id = params.get("campus_id")
        if campus_id:
            _require_dict_id(Campus, campus_id, "campus_id")
            queryset = queryset.filter(location__campus_id=campus_id)

        location_id = params.get("location_id")
        location = None
        if location_id:
            location = Location.objects.filter(pk=location_id).first()
            if location is None:
                raise ApiError(400, "VALIDATION_ERROR", "请检查填写内容", {"location_id": ["地点不存在"]})
            if campus_id and location.campus_id != campus_id:
                raise ApiError(
                    400,
                    "VALIDATION_ERROR",
                    "请检查填写内容",
                    {"location_id": ["该地点不属于所选校区"]},
                )
            queryset = queryset.filter(location_id=location_id)

        occurred_from = params.get("occurred_from")
        occurred_to = params.get("occurred_to")
        from_dt = _parse_datetime(occurred_from, "occurred_from") if occurred_from else None
        to_dt = _parse_datetime(occurred_to, "occurred_to") if occurred_to else None
        if from_dt and to_dt and from_dt > to_dt:
            raise ApiError(
                400,
                "VALIDATION_ERROR",
                "请检查填写内容",
                {"occurred_to": ["结束时间不能早于开始时间"]},
            )
        if from_dt:
            queryset = queryset.filter(occurred_at__gte=from_dt)
        if to_dt:
            queryset = queryset.filter(occurred_at__lte=to_dt)

        sort = params.get("sort") or "latest"
        if sort not in SORT_CHOICES:
            raise ApiError(
                400,
                "VALIDATION_ERROR",
                "请检查填写内容",
                {"sort": ["排序只能是 latest 或 occurred_latest"]},
            )
        ordering = ["-created_at", "-id"] if sort == "latest" else ["-occurred_at", "-id"]
        queryset = queryset.order_by(*ordering)

        pagination = PageQuery(data={name: params[name] for name in ("page", "page_size") if name in params})
        pagination.is_valid(raise_exception=True)
        page, page_size = (pagination.validated_data[name] for name in ("page", "page_size"))
        total = queryset.count()
        offset = (page - 1) * page_size
        rows = list(queryset[offset:offset + page_size]) if offset < total else []
        publishers = publisher_summaries(rows)
        items = [post_summary(post, publishers=publishers) for post in rows]
        return ok(page_payload(items, total, page, page_size), message="查询成功")

    def post(self, request):
        actor = require_actor(request)
        _reject_unknown(request.data, CREATE_FIELDS)

        serializer = PostCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if data["post_type"] == Post.POST_TYPE_FOUND:
            require_campus_verified(actor)

        request_id = data.get("request_id") or None
        if request_id:
            existing = Post.objects.filter(
                publisher_id=actor.id, request_id=request_id
            ).first()
            if existing is not None:
                # 同一发布者的同一 request_id：返回首次创建的那条，不再新建
                return ok(post_detail(existing, include_private=True), message="该 request_id 已创建过信息")

        location = Location.objects.select_related("campus").get(pk=data["location_id"])
        try:
            with transaction.atomic():
                post = Post.objects.create(
                    publisher_id=actor.id,
                    post_type=data["post_type"],
                    title=data["title"],
                    description=data["description"],
                    category_id=data["category_id"],
                    location=location,
                    location_detail=data.get("location_detail") or "",
                    occurred_at=data["occurred_at"],
                    handover_note=data.get("handover_note"),
                    status=Post.STATUS_OPEN,
                    request_id=request_id,
                )
                _bind_images(post, data.get("image_ids") or [], actor)
        except IntegrityError:
            if request_id is None:
                raise
            existing = Post.objects.filter(
                publisher_id=actor.id, request_id=request_id
            ).first()
            if existing is not None:
                return ok(post_detail(existing, include_private=True), message="该 request_id 已创建过信息")
            raise

        return ok(post_detail(post, include_private=True), message="发布成功", status=201)


# ---------------------------------------------------------------- GET/PATCH /posts/{id}
class PostDetailView(APIView):
    def get(self, request, pk):
        post = _load_post(pk)
        actor = current_actor(request)
        if post.status == Post.STATUS_WITHDRAWN and not (
            actor is not None and actor.id == post.publisher_id
        ):
            # 撤回信息对非本人一律 404，不暴露存在性
            raise ApiError(404, "NOT_FOUND", "信息不存在")
        return ok(post_detail(post, include_private=actor is not None), message="查询成功")

    def patch(self, request, pk):
        actor = require_actor(request)
        _reject_unknown(request.data, PATCH_FIELDS, hint="该字段不可修改（只读或不允许编辑）")
        if len(list(request.data.keys())) == 0:
            raise ApiError(
                400, "VALIDATION_ERROR", "请检查填写内容", {"non_field_errors": ["至少提交一个字段"]}
            )

        patch = PostPatchSerializer(data=request.data)
        patch.is_valid(raise_exception=True)
        values = patch.validated_data

        with transaction.atomic():
            post = _load_owned_post(pk, actor)
            if post.status not in (Post.STATUS_OPEN, Post.STATUS_WITHDRAWN):
                raise ApiError(
                    409,
                    "STATE_CONFLICT",
                    "交接中或已完成的信息不能编辑",
                    {"status": [f"当前状态 {post.status} 不允许编辑"]},
                )

            # ---- 合并后的整体校验 ----
            occurred_at = values.get("occurred_at", post.occurred_at)
            if occurred_at > timezone.now():
                raise ApiError(
                    400, "VALIDATION_ERROR", "请检查填写内容", {"occurred_at": ["时间不能晚于当前时间"]}
                )
            if "handover_note" in values:
                note = (values.get("handover_note") or "").strip() or None
            else:
                note = post.handover_note
            if post.post_type == Post.POST_TYPE_FOUND and "handover_note" in values and not note:
                raise ApiError(
                    400,
                    "VALIDATION_ERROR",
                    "请检查填写内容",
                    {"handover_note": ["招领信息必须填写交接说明（1～200 字）"]},
                )
            if post.post_type == Post.POST_TYPE_LOST and note:
                raise ApiError(
                    400, "VALIDATION_ERROR", "请检查填写内容", {"handover_note": ["失物信息不能填写交接说明"]}
                )

            if "title" in values:
                post.title = values["title"]
            if "description" in values:
                post.description = values["description"]
            if "location_detail" in values:
                post.location_detail = values["location_detail"]
            if "category_id" in values:
                post.category_id = values["category_id"]
            if "location_id" in values:
                location = Location.objects.select_related("campus").get(pk=values["location_id"])
                post.location = location
            if "occurred_at" in values:
                post.occurred_at = values["occurred_at"]
            post.handover_note = note
            post.updated_at = timezone.now()
            post.save()

            if "image_ids" in values:
                _bind_images(post, values["image_ids"], actor, replace=True)

        return ok(post_detail(post, include_private=True), message="修改成功")


# ---------------------------------------------------------------- 状态操作
class PostWithdrawView(APIView):
    def post(self, request, pk):
        actor = require_actor(request)
        with transaction.atomic():
            post = _load_owned_post(pk, actor)
            transit(post, Post.STATUS_WITHDRAWN, actor, reason="withdraw")
            # 撤回与关闭 C 的待处理申请必须同一事务：C 调用失败会抛出并回滚
            close_pending_claims(post.id, reason="post_withdrawn")
        return ok(post_detail(post, include_private=True), message="已撤回")


class PostRestoreView(APIView):
    def post(self, request, pk):
        actor = require_actor(request)
        with transaction.atomic():
            post = _load_owned_post(pk, actor)
            transit(post, Post.STATUS_OPEN, actor, reason="restore")
        return ok(post_detail(post, include_private=True), message="已恢复")


class PostResolveView(APIView):
    def post(self, request, pk):
        actor = require_actor(request)
        if not hasattr(request.data, "get"):
            raise ApiError(
                400, "VALIDATION_ERROR", "请检查填写内容", {"non_field_errors": ["请求体必须是 JSON 对象"]}
            )
        note = str(request.data.get("resolve_note") or "").strip()
        if not note or len(note) < 5 or len(note) > 200:
            raise ApiError(
                400,
                "VALIDATION_ERROR",
                "请检查填写内容",
                {"resolve_note": ["办结说明不能为空，且长度为 5～200 字"]},
            )

        with transaction.atomic():
            post = _load_owned_post(pk, actor)
            if post.post_type != Post.POST_TYPE_LOST:
                raise ApiError(
                    409,
                    "STATE_CONFLICT",
                    "招领信息不能自行办结，必须走双方确认的认领流程",
                    {"post_type": ["仅失物信息支持自行办结"]},
                )
            transit(post, Post.STATUS_COMPLETED, actor, reason=note)
        return ok(post_detail(post, include_private=True), message="已标记找回")


class PostReopenView(APIView):
    def post(self, request, pk):
        actor = require_actor(request)
        with transaction.atomic():
            post = _load_owned_post(pk, actor)
            if post.status != Post.STATUS_COMPLETED:
                raise ApiError(
                    409,
                    "STATE_CONFLICT",
                    f"信息当前状态为 {post.status}，不能撤销完成",
                    {"status": [f"当前状态 {post.status}"]},
                )
            if has_completed_claim(post.id):
                raise ApiError(
                    409,
                    "STATE_CONFLICT",
                    "该信息已有双方确认完成的认领记录，需先由认领模块处理",
                    {"claim": ["存在 completed 认领记录"]},
                )
            transit(post, Post.STATUS_OPEN, actor, reason="reopen")
        return ok(post_detail(post, include_private=True), message="已撤销完成")


# ---------------------------------------------------------------- 图片
def _parse_bool(raw, default: bool):
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    value = str(raw).strip().lower()
    if value in ("true", "1"):
        return True
    if value in ("false", "0"):
        return False
    return None


class PostImageUploadView(APIView):
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        actor = require_actor(request)

        upload = request.FILES.get("file")
        if upload is None:
            raise ApiError(400, "VALIDATION_ERROR", "请检查填写内容", {"file": ["请选择要上传的图片"]})

        alt_text = str(request.data.get("alt_text") or "").strip()
        if not 5 <= len(alt_text) <= 100 or alt_text.casefold() in {"image", "photo"}:
            raise ApiError(
                400,
                "VALIDATION_ERROR",
                "请检查填写内容",
                {"alt_text": ["替代文字不能为空，且长度为 5～100 字"]},
            )

        is_public = _parse_bool(request.data.get("is_public"), default=True)
        if is_public is None:
            raise ApiError(
                400, "VALIDATION_ERROR", "请检查填写内容", {"is_public": ["is_public 只能是 true 或 false"]}
            )

        if upload.size is not None and upload.size > MAX_IMAGE_BYTES:
            raise ApiError(
                413,
                "FILE_TOO_LARGE",
                "图片超过 5 MiB 限制",
                {"file": ["单张图片不能超过 5 MiB"]},
            )

        declared = (upload.content_type or "").lower()
        if declared and declared not in ALLOWED_MIME:
            raise ApiError(415, "UNSUPPORTED_MEDIA_TYPE", "图片格式不支持，仅支持 jpeg/png/webp")

        payload = upload.read()
        if len(payload) > MAX_IMAGE_BYTES:
            raise ApiError(
                413, "FILE_TOO_LARGE", "图片超过 5 MiB 限制", {"file": ["单张图片不能超过 5 MiB"]}
            )
        mime_type = detect_image_mime(payload)  # 实际解码校验，失败返回 415

        image = PostImage(owner_id=actor.id, alt_text=alt_text, is_public=is_public)
        image.save_bytes(payload, mime_type)
        try:
            image.save()
        except Exception:
            image.delete_file()
            raise
        return ok(image_view(image), message="上传成功", status=201)


class PostImageContentView(APIView):
    def get(self, request, pk):
        image = PostImage.objects.select_related("post").filter(pk=pk).first()
        if image is None:
            raise ApiError(404, "NOT_FOUND", "图片不存在")

        actor = current_actor(request)
        is_actor = actor is not None

        if image.post_id is None:
            # 未绑定图片仅上传者可读
            if not (is_actor and actor.id == image.owner_id):
                raise ApiError(404, "NOT_FOUND", "图片不存在")
        else:
            post = image.post
            if post.status == Post.STATUS_WITHDRAWN:
                # 撤回后全部图片一律不可读，仅发布者例外
                if not (is_actor and actor.id == post.publisher_id):
                    raise ApiError(404, "NOT_FOUND", "图片不存在")
            elif not image.is_public and not is_actor:
                raise ApiError(401, "UNAUTHENTICATED", "该图片需要登录后查看")

        try:
            handle = image.file.open("rb")
        except (FileNotFoundError, OSError):
            logger.error("图片文件丢失: image=%s path=%s", image.pk, image.file.name)
            raise ApiError(404, "NOT_FOUND", "图片不存在")

        response = FileResponse(handle, content_type=image.mime_type)
        response["Cache-Control"] = "no-store"
        response["X-Content-Type-Options"] = "nosniff"
        filename = image.file.name.rsplit("/", 1)[-1]
        response["Content-Disposition"] = f'inline; filename="{filename}"'
        return response


class DemoPostsQuery(PageQuery):
    mine = drf_serializers.ChoiceField(choices=("true", "false"), required=False, default="false")


class DemoPostsView(OptionalAuthAPIView):
    def initial(self, request, *args, **kwargs):
        require_demo_mode()
        super().initial(request, *args, **kwargs)

    def get(self, request):
        filters = parse_query(DemoPostsQuery, request)
        owner_id = require_actor(request).id if filters["mine"] == "true" else None
        page = filters["page"]
        page_size = filters["page_size"]
        records, total = services.page_posts(owner_id, page, page_size)
        return ok(page_payload([shared_post_summary(record) for record in records], total, page, page_size))
