"""展示组装（架构阶段 3）：把模型拼成契约规定的 ``PostSummary`` / ``PostDetail``。

只做"取数据 → 拼结构"，不做权限判断（权限在视图与 images 里），也不做检索（在 query 里）。
v0.5 新增的"发布者查不到时降级为占位摘要"也在这里统一处理，列表与详情共用一套逻辑。
"""

from __future__ import annotations

from common.clock import iso
from common.contracts import (
    Label,
    Post as PostRecord,
    UserSummary,
    deleted_user_summary,
    post_summary as shared_post_summary,
)

from posts.images import image_view  # noqa: F401  （对外仍从本模块导出）


def publisher_summaries(posts) -> dict[str, UserSummary]:
    """批量取发布者摘要；A 那边缺失的用户由 :func:`publisher_of` 兜底。"""
    from identity.services import get_user_summaries

    return get_user_summaries({post.publisher_id for post in posts})


def publisher_of(post, publishers: dict[str, UserSummary]) -> UserSummary:
    publisher = publishers.get(post.publisher_id)
    if publisher is None:
        # 账号被注销、数据被清理，或 A 模块暂时不可用：降级而不是 500
        return deleted_user_summary(post.publisher_id)
    return publisher


def post_record(
    post,
    images=None,
    *,
    publishers: dict[str, UserSummary] | None = None,
) -> PostRecord:
    if publishers is None:
        publishers = publisher_summaries((post,))
    if images is None:
        images = list(post.images.all())
    cover = next((image for image in images if image.is_public), None)
    return PostRecord(
        id=str(post.id),
        post_type=post.post_type,
        title=post.title,
        category=Label(post.category_id, post.category.name),
        campus=Label(post.location.campus_id, post.location.campus.name),
        location=Label(post.location_id, post.location.name),
        occurred_at=post.occurred_at,
        status=post.status,
        cover_image=image_view(cover) if cover is not None else None,
        publisher=publisher_of(post, publishers),
        created_at=post.created_at,
        updated_at=post.updated_at,
    )


def post_summary(post, images=None, *, publishers=None) -> dict:
    record = post_record(post, images, publishers=publishers)
    data = shared_post_summary(record)
    data["cover_image"] = record.cover_image
    return data


def post_detail(post, images=None, *, include_private: bool = False) -> dict:
    if images is None:
        images = list(post.images.all())
    data = post_summary(post, images)
    data.update(
        description=post.description,
        location_detail=post.location_detail,
        handover_note=post.handover_note,
        images=[image_view(image) for image in images if include_private or image.is_public],
        completed_at=iso(post.completed_at),
    )
    return data


__all__ = [
    "image_view",
    "publisher_summaries",
    "deleted_user_summary",
    "publisher_of",
    "post_record",
    "post_summary",
    "post_detail",
]
