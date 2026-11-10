"""B 子系统 HTTP 接口（契约 5.1 / 5.2 / 5.3 / 5.4）。

本模块是**薄壳**：只做参数解析、身份与权限、事务边界、响应组装。真正的规则分布在：

- ``posts.constants``       —— 契约常量（状态、字段白名单、分页、错误码）
- ``posts.query``           —— 列表检索（筛选 / 排序 / 分页）
- ``posts.dictionary``      —— 校区 / 分类 / 地点字典
- ``posts.images``          —— 图片上传、可见性判定、内容响应、清理
- ``posts.browse``          —— PostSummary / PostDetail 组装
- ``workflow.transitions``  —— 状态机（action 驱动）

接口全部挂在 ``/api/v1`` 下，成功走 ``common.responses.ok()``，失败由统一异常处理器转错误信封。
"""

from __future__ import annotations

import logging

from django.db import IntegrityError, transaction
from django.db.models import Q
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
from posts import constants as C
from posts import dictionary, images, query, services
from posts.browse import post_detail, post_summary, publisher_summaries
from posts.models import Post, PostImage
from posts.serializers import PostCreateSerializer, PostPatchSerializer
from workflow.transitions import transit

logger = logging.getLogger("b.posts")


# ---------------------------------------------------------------- 小工具
def _reject_unknown(data, allowed, hint: str = "未知字段或只读字段，不能由客户端提交") -> None:
    if not hasattr(data, "keys"):
        raise ApiError(
            400,
            C.CODE_VALIDATION_ERROR,
            "请检查填写内容",
            {"non_field_errors": ["请求体必须是 JSON 对象"]},
        )
    unknown = [key for key in data.keys() if key not in allowed]
    if unknown:
        raise ApiError(
            400,
            C.CODE_VALIDATION_ERROR,
            "请检查填写内容",
            {key: [hint] for key in unknown},
        )


def _coerce_image_ids(raw_ids) -> list[int]:
    result = []
    for raw in raw_ids:
        try:
            result.append(int(raw))
        except (TypeError, ValueError):
            raise ApiError(
                400,
                C.CODE_VALIDATION_ERROR,
                "请检查填写内容",
                {"image_ids": [f"图片 ID 不合法: {raw}"]},
            )
    return result


def _load_post(pk, *, for_update: bool = False, with_images: bool = True):
    """按主键取信息；``for_update`` 时仅锁定信息行。"""
    if for_update:
        queryset = services.lock_post_rows()
    else:
        queryset = Post.objects.select_related(*query.LIST_RELATED)
    if with_images:
        queryset = queryset.prefetch_related("images")
    post = queryset.filter(pk=pk).first()
    if post is None:
        raise ApiError(404, C.CODE_NOT_FOUND, "信息不存在")
    return post


def _load_owned_post(pk, actor):
    """写操作加载：非本人对已撤回信息返回 404，其余返回 403。"""
    post = _load_post(pk, for_update=True, with_images=False)
    if post.publisher_id != actor.id:
        if post.status == C.STATUS_WITHDRAWN:
            raise ApiError(404, C.CODE_NOT_FOUND, "信息不存在")
        raise ApiError(403, C.CODE_FORBIDDEN, "只能操作本人发布的信息")
    return post


def _bind_images(post: Post, raw_ids, actor, *, replace: bool = False) -> None:
    """把图片按数组顺序绑定到信息上；必须与信息保存处于同一事务（契约 3.6）。"""
    ids = _coerce_image_ids(raw_ids or [])
    if not ids and not replace:
        return
    if len(set(ids)) != len(ids):
        raise ApiError(
            400, C.CODE_VALIDATION_ERROR, "请检查填写内容", {"image_ids": ["图片 ID 不能重复"]}
        )
    if len(ids) > C.MAX_IMAGES:
        raise ApiError(
            400,
            C.CODE_VALIDATION_ERROR,
            "请检查填写内容",
            {"image_ids": [f"每条信息最多 {C.MAX_IMAGES} 张图片"]},
        )

    selected = Q(id__in=ids)
    if replace:
        selected |= Q(post_id=post.id)
    rows = PostImage.objects.select_for_update().filter(selected).order_by("id")
    found = {image.id: image for image in rows}
    if replace:
        # 整体替换：先解绑不在新数组里的图片
        post.images.exclude(id__in=ids).update(post=None, sort_order=0)
    for index, image_id in enumerate(ids):
        image = found.get(image_id)
        if image is None:
            raise ApiError(
                400,
                C.CODE_VALIDATION_ERROR,
                "请检查填写内容",
                {"image_ids": [f"图片 {image_id} 不存在"]},
            )
        if image.owner_id != actor.id:
            raise ApiError(403, C.CODE_FORBIDDEN, "只能绑定本人上传的图片")
        if image.post_id is not None and image.post_id != post.id:
            raise ApiError(
                400,
                C.CODE_VALIDATION_ERROR,
                "请检查填写内容",
                {"image_ids": ["图片已绑定其他信息"]},
            )
        image.post = post
        image.sort_order = index
        image.save(update_fields=["post", "sort_order"])


# ---------------------------------------------------------------- POST /posts, GET /posts
class PostCollectionView(APIView):
    def get(self, request):
        rows, total, page, page_size = query.search_posts(request.query_params)
        publishers = publisher_summaries(rows)
        items = [post_summary(post, publishers=publishers) for post in rows]
        return ok(page_payload(items, total, page, page_size), message="查询成功")

    def post(self, request):
        actor = require_actor(request)
        _reject_unknown(request.data, C.CREATE_FIELDS)

        serializer = PostCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if data["post_type"] == C.POST_TYPE_FOUND:
            require_campus_verified(actor)

        request_id = data.get("request_id") or None
        if request_id:
            existing = Post.objects.filter(publisher_id=actor.id, request_id=request_id).first()
            if existing is not None:
                # 同一发布者的同一 request_id：返回首次创建的那条，不再新建（契约 5.2 幂等）
                return ok(
                    post_detail(existing, include_private=True),
                    message="该 request_id 已创建过信息",
                )

        location = dictionary.resolve_location(data["location_id"])
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
                    status=C.STATUS_OPEN,
                    request_id=request_id,
                )
                _bind_images(post, data.get("image_ids") or [], actor)
        except IntegrityError:
            if request_id is None:
                raise
            existing = Post.objects.filter(publisher_id=actor.id, request_id=request_id).first()
            if existing is not None:
                return ok(
                    post_detail(existing, include_private=True),
                    message="该 request_id 已创建过信息",
                )
            raise

        return ok(post_detail(post, include_private=True), message="发布成功", status=201)


# ---------------------------------------------------------------- GET/PATCH /posts/{id}
class PostDetailView(APIView):
    def get(self, request, pk):
        post = _load_post(pk)
        actor = current_actor(request)
        if post.status == C.STATUS_WITHDRAWN and not (
            actor is not None and actor.id == post.publisher_id
        ):
            # 撤回信息对非本人一律 404，不暴露存在性
            raise ApiError(404, C.CODE_NOT_FOUND, "信息不存在")
        return ok(post_detail(post, include_private=actor is not None), message="查询成功")

    def patch(self, request, pk):
        actor = require_actor(request)
        _reject_unknown(
            request.data, C.PATCH_FIELDS, hint="该字段不可修改（只读或不允许编辑）"
        )
        if len(list(request.data.keys())) == 0:
            raise ApiError(
                400,
                C.CODE_VALIDATION_ERROR,
                "请检查填写内容",
                {"non_field_errors": ["至少提交一个字段"]},
            )

        patch = PostPatchSerializer(data=request.data)
        patch.is_valid(raise_exception=True)
        values = patch.validated_data

        with transaction.atomic():
            post = _load_owned_post(pk, actor)
            if post.status not in (C.STATUS_OPEN, C.STATUS_WITHDRAWN):
                raise ApiError(
                    409,
                    C.CODE_STATE_CONFLICT,
                    "交接中或已完成的信息不能编辑",
                    {"status": [f"当前状态 {post.status} 不允许编辑"]},
                )

            # ---- 合并后的整体校验 ----
            occurred_at = values.get("occurred_at", post.occurred_at)
            if occurred_at > timezone.now():
                raise ApiError(
                    400,
                    C.CODE_VALIDATION_ERROR,
                    "请检查填写内容",
                    {"occurred_at": ["时间不能晚于当前时间"]},
                )

            # handover_note 只在本次显式提交时校验：存量数据若已有非空值，
            # 不该因为改了标题之类的无关字段就整体 400。
            if "handover_note" in values:
                note = (values.get("handover_note") or "").strip() or None
                if post.post_type == C.POST_TYPE_FOUND and not note:
                    raise ApiError(
                        400,
                        C.CODE_VALIDATION_ERROR,
                        "请检查填写内容",
                        {"handover_note": [f"招领信息必须填写交接说明（{C.HANDOVER_MIN}～{C.HANDOVER_MAX} 字）"]},
                    )
                if post.post_type == C.POST_TYPE_LOST and note:
                    raise ApiError(
                        400,
                        C.CODE_VALIDATION_ERROR,
                        "请检查填写内容",
                        {"handover_note": ["失物信息不能填写交接说明"]},
                    )
                post.handover_note = note

            if "title" in values:
                post.title = values["title"]
            if "description" in values:
                post.description = values["description"]
            if "location_detail" in values:
                post.location_detail = values["location_detail"]
            if "category_id" in values:
                post.category_id = values["category_id"]
            if "location_id" in values:
                post.location = dictionary.resolve_location(values["location_id"])
            if "occurred_at" in values:
                post.occurred_at = values["occurred_at"]
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
            transit(post, "withdraw", actor, reason="withdraw")
            # 撤回与关闭 C 的待处理申请必须同一事务：C 调用失败会抛出并回滚
            close_pending_claims(post.id, reason="post_withdrawn")
        return ok(post_detail(post, include_private=True), message="已撤回")


class PostRestoreView(APIView):
    def post(self, request, pk):
        actor = require_actor(request)
        with transaction.atomic():
            post = _load_owned_post(pk, actor)
            transit(post, "restore", actor, reason="restore")
        return ok(post_detail(post, include_private=True), message="已恢复")


class PostResolveView(APIView):
    def post(self, request, pk):
        actor = require_actor(request)
        if not hasattr(request.data, "get"):
            raise ApiError(
                400,
                C.CODE_VALIDATION_ERROR,
                "请检查填写内容",
                {"non_field_errors": ["请求体必须是 JSON 对象"]},
            )
        note = str(request.data.get("resolve_note") or "").strip()
        if not note or len(note) < 5 or len(note) > 200:
            raise ApiError(
                400,
                C.CODE_VALIDATION_ERROR,
                "请检查填写内容",
                {"resolve_note": ["办结说明不能为空，且长度为 5～200 字"]},
            )

        with transaction.atomic():
            post = _load_owned_post(pk, actor)
            # 招领不能走自行办结；状态与类型校验统一在状态机里做
            transit(post, "resolve", actor, reason=note)
        return ok(post_detail(post, include_private=True), message="已标记找回")


class PostReopenView(APIView):
    def post(self, request, pk):
        actor = require_actor(request)
        with transaction.atomic():
            post = _load_owned_post(pk, actor)
            if has_completed_claim(post.id):
                raise ApiError(
                    409,
                    C.CODE_STATE_CONFLICT,
                    "该信息已有双方确认完成的认领记录，需先由认领模块处理",
                    {"claim": ["存在 completed 认领记录"]},
                )
            transit(post, "reopen", actor, reason="reopen")
        return ok(post_detail(post, include_private=True), message="已撤销完成")


# ---------------------------------------------------------------- 图片
class PostImageUploadView(APIView):
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        actor = require_actor(request)
        is_public = images.parse_bool(request.data.get("is_public"), default=True)
        image = images.save_image(
            request.FILES.get("file"),
            alt_text=request.data.get("alt_text"),
            is_public=is_public,
            owner_id=actor.id,
        )
        return ok(images.image_view(image), message="上传成功", status=201)


class PostImageContentView(APIView):
    def get(self, request, pk):
        image = PostImage.objects.select_related("post").filter(pk=pk).first()
        if image is None:
            raise ApiError(404, C.CODE_NOT_FOUND, "图片不存在")

        actor = current_actor(request)
        decision = images.can_view(
            image,
            viewer_id=actor.id if actor is not None else None,
            post_status=image.post.status if image.post_id is not None else None,
        )
        if decision == images.ACCESS_NOT_FOUND:
            raise ApiError(404, C.CODE_NOT_FOUND, "图片不存在")
        if decision == images.ACCESS_UNAUTHENTICATED:
            raise ApiError(401, C.CODE_UNAUTHENTICATED, "该图片需要登录后查看")
        return images.open_content(image)


# ---------------------------------------------------------------- 演示接口（契约 5.5）
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
        return ok(
            page_payload([shared_post_summary(record) for record in records], total, page, page_size)
        )
