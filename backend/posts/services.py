"""B's in-process services for C, with post-first locking in the caller's transaction."""

from __future__ import annotations

from collections.abc import Iterable

from django.conf import settings
from common.contracts import Post as PostRecord
from common.errors import AppError
from posts.models import Post
from posts.presenters import post_record, publisher_summaries
from workflow.transitions import transit

PUBLIC_STATUSES = frozenset(Post.PUBLIC_STATUSES)
_RELATED = ("category", "location__campus")


def _records(rows) -> list[PostRecord]:
    rows = list(rows)
    publishers = publisher_summaries(rows)
    return [post_record(row, publishers=publishers) for row in rows]


def get_post_for_claim(post_id: str, *, lock: bool = False) -> PostRecord | None:
    """Return the post C needs; ``lock=True`` takes the row lock for this transaction."""
    if lock:
        row = Post.objects.select_for_update().filter(pk=post_id).first()
        return post_record(row) if row is not None else None
    row = Post.objects.select_related(*_RELATED).prefetch_related("images").filter(pk=post_id).first()
    return post_record(row) if row is not None else None


def get_posts_for_claims(post_ids: Iterable[str], *, lock: bool = False) -> dict[str, PostRecord]:
    """Batch read for list responses; avoids one query per claim."""
    ids = set(post_ids)
    if not ids:
        return {}
    queryset = Post.objects.select_for_update() if lock else Post.objects.select_related(*_RELATED)
    return {record.id: record for record in _records(queryset.filter(pk__in=ids).prefetch_related("images"))}


def set_handover_state(post_id: str, transition: str) -> PostRecord:
    """Apply ``reserve``/``complete``/``reopen`` to the post inside the caller's transaction."""
    transitions = {
        "reserve": ("open", "in_handover"),
        "complete": ("in_handover", "completed"),
        "reopen": ("in_handover", "open"),
    }
    if transition not in transitions:
        raise ValueError(f"未知的交接状态转换：{transition}")
    before, after = transitions[transition]

    row = Post.objects.select_for_update().filter(pk=post_id).first()
    if row is None:
        raise AppError(404, "NOT_FOUND", "信息不存在")
    if row.status != before:
        raise AppError(409, "STATE_CONFLICT", "信息状态已变化")

    transit(row, after, actor="c:claim-service", reason=f"c:{transition}")
    return post_record(row)


def list_match_candidates(source: PostRecord) -> list[PostRecord]:
    """Open, opposite-type posts in the same campus and category, excluding the publisher's."""
    opposite = "found" if source.post_type == "lost" else "lost"
    rows = (
        Post.objects.select_related(*_RELATED)
        .filter(
            post_type=opposite,
            status="open",
            category_id=source.category.id,
            location__campus_id=source.campus.id,
        )
        .exclude(publisher_id=source.publisher.id)
        .order_by("created_at", "id")
    )
    return _records(rows.prefetch_related("images"))


def page_posts(
    owner_id: str | None, page: int, page_size: int
) -> tuple[list[PostRecord], int]:
    """Public page for anonymous visitors, or all statuses of one publisher."""
    queryset = Post.objects.select_related(*_RELATED)
    if owner_id is None:
        queryset = queryset.filter(status__in=("open", "in_handover"))
    else:
        queryset = queryset.filter(publisher_id=owner_id)
    total = queryset.count()
    offset = (page - 1) * page_size
    rows = queryset.order_by("-created_at", "-id")[offset : offset + page_size]
    return _records(rows.prefetch_related("images")), total


def database_is_isolated() -> bool:
    """Guard used by the demo seed command; never aimed at a shared or production server."""
    database = settings.DATABASES["default"]
    return (
        database["ENGINE"] == "django.db.backends.mysql"
        and database["HOST"] in {"127.0.0.1", "localhost", "::1"}
        and database["PORT"] == "33307"
        and database["NAME"] == "claim_dev"
    )
