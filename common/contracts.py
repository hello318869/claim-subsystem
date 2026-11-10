"""Record shapes shared with the other subsystems (contract §3.9).

``identity`` and ``posts`` are demo stand-ins for A and B, but they hand C exactly the records
the contract defines, so swapping in the real modules only means replacing the adapter
functions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from common.clock import iso

POST_IMAGE_FIELDS = ("id", "url", "mime_type", "size_bytes", "sort_order", "alt_text")


@dataclass(frozen=True)
class Label:
    id: str
    name: str


@dataclass(frozen=True)
class UserSummary:
    id: str
    nickname: str
    is_campus_verified: bool
    verification_mode: str | None


@dataclass(frozen=True)
class Post:
    id: str
    post_type: str
    title: str
    category: Label
    campus: Label
    location: Label
    occurred_at: datetime
    status: str
    cover_image: dict | None
    publisher: UserSummary
    created_at: datetime
    updated_at: datetime


def user_summary(user: UserSummary) -> dict:
    return {
        "id": user.id,
        "nickname": user.nickname,
        "is_campus_verified": user.is_campus_verified,
        "verification_mode": user.verification_mode,
    }


def post_summary(post: Post) -> dict:
    return {
        "id": post.id,
        "post_type": post.post_type,
        "title": post.title,
        "category": {"id": post.category.id, "name": post.category.name},
        "campus": {"id": post.campus.id, "name": post.campus.name},
        "location": {"id": post.location.id, "name": post.location.name},
        "occurred_at": iso(post.occurred_at),
        "status": post.status,
        "cover_image": (
            {field: post.cover_image[field] for field in POST_IMAGE_FIELDS}
            if post.cover_image is not None
            else None
        ),
        "publisher": user_summary(post.publisher),
        "created_at": iso(post.created_at),
        "updated_at": iso(post.updated_at),
    }
