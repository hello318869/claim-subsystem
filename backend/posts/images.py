"""图片资源的唯一实现（架构阶段 3：V-2 图片存储与可见性单点裁决）。

上传校验、传输格式、可见性判定、清理都在这里。视图只负责取参数与写响应，
不再自己判断 ``is_public`` 与状态（契约 v0.5 把可见性规则写得很细，散落各处的判断极易走偏）。

契约依据：§3.6（图片字段与规则）、§5.1（/post-images 接口）、v0.5 第 265/272/391 行的可见性表述。
"""

from __future__ import annotations

import logging

from django.http import FileResponse

from common.exceptions import ApiError
from posts import constants as C
from posts.imagetype import ALLOWED_MIME, MAX_IMAGE_BYTES, detect_image_mime
from posts.models import Post, PostImage

logger = logging.getLogger("b.posts.images")

#: 可见性判定结果，视图据此映射成 200 / 401 / 404。
ACCESS_ALLOW = "allow"
ACCESS_UNAUTHENTICATED = "unauthenticated"
ACCESS_NOT_FOUND = "not_found"

IMAGE_CONTENT_PATH = "/api/v1/post-images/{image_id}/content"


# ---------------------------------------------------------------- 展示
def image_url(image: PostImage) -> str:
    return IMAGE_CONTENT_PATH.format(image_id=image.id)


def image_view(image: PostImage) -> dict:
    """``PostImageView``（契约 3.6）：id / url / mime_type / size_bytes / sort_order /
    alt_text / is_public。"""
    return {
        "id": str(image.id),
        "url": image_url(image),
        "mime_type": image.mime_type,
        "size_bytes": image.size_bytes,
        "sort_order": image.sort_order,
        "alt_text": image.alt_text,
        "is_public": image.is_public,
    }


# ---------------------------------------------------------------- 上传
def parse_bool(raw, default: bool) -> bool | None:
    """表单里的 ``true/false/1/0``；无法解析返回 ``None`` 由调用方报 400。"""
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


def _validate_alt_text(raw) -> str:
    alt_text = str(raw or "").strip()
    if not C.ALT_TEXT_MIN <= len(alt_text) <= C.ALT_TEXT_MAX:
        raise ApiError(
            400,
            C.CODE_VALIDATION_ERROR,
            "请检查填写内容",
            {"alt_text": [f"替代文字不能为空，且长度为 {C.ALT_TEXT_MIN}～{C.ALT_TEXT_MAX} 字"]},
        )
    if alt_text.casefold() in {"image", "photo"}:
        # 契约 3.6：不得只写"图片""照片"这类无信息量内容
        raise ApiError(
            400,
            C.CODE_VALIDATION_ERROR,
            "请检查填写内容",
            {"alt_text": ["替代文字需要描述图片内容，不能只写 image 或 photo"]},
        )
    return alt_text


def save_image(upload, *, alt_text, is_public, owner_id) -> PostImage:
    """校验并落盘一张图片，返回未绑定到任何信息的 ``PostImage``。

    顺序与契约一致：先看声明的大小与 MIME（便宜的检查），再读字节做真实解码校验
    （客户端声明的 ``Content-Type`` 不可信，SVG 也必须在这里被挡住）。
    """
    if upload is None:
        raise ApiError(
            400, C.CODE_VALIDATION_ERROR, "请检查填写内容", {"file": ["请选择要上传的图片"]}
        )

    alt_text = _validate_alt_text(alt_text)

    if is_public is None:
        raise ApiError(
            400,
            C.CODE_VALIDATION_ERROR,
            "请检查填写内容",
            {"is_public": ["is_public 只能是 true 或 false"]},
        )

    if upload.size is not None and upload.size > MAX_IMAGE_BYTES:
        raise ApiError(
            413,
            C.CODE_FILE_TOO_LARGE,
            "图片超过 5 MiB 限制",
            {"file": ["单张图片不能超过 5 MiB"]},
        )

    declared = (upload.content_type or "").lower()
    if declared and declared not in ALLOWED_MIME:
        raise ApiError(415, C.CODE_UNSUPPORTED_MEDIA_TYPE, "图片格式不支持，仅支持 jpeg/png/webp")

    payload = upload.read()
    if len(payload) > MAX_IMAGE_BYTES:
        raise ApiError(
            413,
            C.CODE_FILE_TOO_LARGE,
            "图片超过 5 MiB 限制",
            {"file": ["单张图片不能超过 5 MiB"]},
        )
    mime_type = detect_image_mime(payload)  # 解码失败直接抛 415

    image = PostImage(owner_id=owner_id, alt_text=alt_text, is_public=is_public)
    image.save_bytes(payload, mime_type)
    try:
        image.save()
    except Exception:
        image.delete_file()
        raise
    return image


# ---------------------------------------------------------------- 可见性
def can_view(image: PostImage, *, viewer_id: str | None, post_status: str | None) -> str:
    """判断某位访问者能否读取图片内容。

    三档（契约 3.6 / v0.5）：

    1. 未绑定图片：只有上传者本人可读，其余一律 404（不暴露存在性）。
    2. 已绑定且信息已撤回：只有发布者可读，其余 404。
    3. 已绑定且未撤回：``is_public=True`` 匿名可读；``is_public=False`` 需要登录，
       但**任何登录用户**都能读（v0.5 修正了"仅发布者"的旧理解）。
    """
    is_authenticated = viewer_id is not None

    if image.post_id is None:
        return ACCESS_ALLOW if viewer_id == image.owner_id else ACCESS_NOT_FOUND

    if post_status == Post.STATUS_WITHDRAWN:
        return ACCESS_ALLOW if viewer_id == image.post.publisher_id else ACCESS_NOT_FOUND

    if image.is_public:
        return ACCESS_ALLOW
    if not is_authenticated:
        return ACCESS_UNAUTHENTICATED
    return ACCESS_ALLOW


def open_content(image: PostImage) -> FileResponse:
    """打开私有存储里的文件并包成 ``FileResponse``。"""
    try:
        handle = image.file.open("rb")
    except (FileNotFoundError, OSError):
        logger.error("图片文件丢失: image=%s path=%s", image.pk, image.file.name)
        raise ApiError(404, C.CODE_NOT_FOUND, "图片不存在")

    response = FileResponse(handle, content_type=image.mime_type)
    response["Cache-Control"] = "no-store"
    response["X-Content-Type-Options"] = "nosniff"
    filename = image.file.name.rsplit("/", 1)[-1]
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    return response


# ---------------------------------------------------------------- 清理
def purge_for_post(post: Post) -> int:
    """物理删除某条信息下的全部图片（文件 + 记录），返回删除数量。

    数据生命周期要求"已撤回立即可见性关闭、90 天删除"，清理任务与撤回流程都走这里，
    确保文件不会残留。``delete_file`` 自身带空文件保护。
    """
    removed = 0
    for image in post.images.all():
        image.delete_file()
        image.delete()
        removed += 1
    return removed
