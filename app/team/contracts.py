"""Public records and the in-process contracts with A and B."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy.orm import Session

from app.clock import iso


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


class IdentityService(Protocol):
    """A resolves its own session token and exposes only public user fields."""

    def require_user(self, session: Session, token: str) -> UserSummary: ...

    def get_user_summaries(
        self, session: Session, user_ids: set[str],
    ) -> Mapping[str, UserSummary]: ...


class PostService(Protocol):
    """B owns Post. Locking reads and writes use the caller's Session."""

    def get_post_for_claim(
        self, session: Session, post_id: str, *, lock: bool = False,
    ) -> Post | None: ...

    def set_handover_state(self, session: Session, post_id: str, transition: str) -> Post: ...

    def list_match_candidates(self, session: Session, source_post: Post) -> Iterable[Post]: ...


def user_summary(user: UserSummary) -> dict:
    return {
        "id": user.id,
        "nickname": user.nickname,
        "is_campus_verified": user.is_campus_verified,
        "verification_mode": user.verification_mode,
    }


def post_summary(post: Post) -> dict:
    image_fields = ("id", "url", "mime_type", "size_bytes", "sort_order", "alt_text")
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
            {field: post.cover_image[field] for field in image_fields}
            if post.cover_image is not None else None
        ),
        "publisher": user_summary(post.publisher),
        "created_at": iso(post.created_at),
        "updated_at": iso(post.updated_at),
    }
