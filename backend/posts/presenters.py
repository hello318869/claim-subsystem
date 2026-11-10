"""Present B's public Post and image records using A's shared identity summary."""

from common.clock import iso
from common.contracts import Label, Post as PostRecord, UserSummary, post_summary as shared_post_summary
from common.errors import AppError


def image_view(image) -> dict:
    return {
        "id": str(image.id),
        "url": f"/api/v1/post-images/{image.id}/content",
        "mime_type": image.mime_type,
        "size_bytes": image.size_bytes,
        "sort_order": image.sort_order,
        "alt_text": image.alt_text,
        "is_public": image.is_public,
    }


def publisher_summaries(posts) -> dict[str, UserSummary]:
    from identity.services import get_user_summaries

    return get_user_summaries({post.publisher_id for post in posts})


def post_record(post, images=None, *, publishers=None) -> PostRecord:
    if publishers is None:
        publishers = publisher_summaries((post,))
    publisher = publishers.get(post.publisher_id)
    if publisher is None:
        raise AppError(500, "INTERNAL_ERROR", "信息发布者不可用")
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
        publisher=publisher,
        created_at=post.created_at,
        updated_at=post.updated_at,
    )


def post_summary(post, images=None, *, publishers=None) -> dict:
    record = post_record(post, images, publishers=publishers)
    data = shared_post_summary(record)
    data["cover_image"] = record.cover_image
    return data


def post_detail(post, images=None, *, include_private=False) -> dict:
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
