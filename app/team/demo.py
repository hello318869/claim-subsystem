"""Local A and B substitutes for contract testing and the team demo."""

from datetime import datetime, timedelta
from hashlib import sha256
from secrets import token_urlsafe
from threading import Lock

from sqlalchemy import DateTime, Index, String, func, select
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.clock import iso, to_db, utcnow
from app.errors import AppError
from app.models import Base
from app.team.contracts import Label, Post, UserSummary, user_summary


DEMO_USERS = {
    user.id: user
    for user in (
        UserSummary("alice", "小林", True, "demo"),
        UserSummary("bob", "小周", True, "demo"),
        UserSummary("finder", "小陈", True, "demo"),
        UserSummary("outsider", "访客", False, None),
    )
}
POST_TIMESTAMP = DateTime().with_variant(DATETIME(fsp=6), "mysql")


class DemoIdentity:
    def __init__(self) -> None:
        self._tokens: dict[str, tuple[str, datetime]] = {}
        self._lock = Lock()

    @staticmethod
    def _digest(token: str) -> str:
        return sha256(token.encode()).hexdigest()

    def issue(self, actor: str) -> dict:
        user = DEMO_USERS.get(actor)
        if user is None:
            raise AppError(400, "VALIDATION_ERROR", "未知的演示身份", field="actor")
        token = token_urlsafe(32)
        now = utcnow()
        expires = now + timedelta(hours=24)
        with self._lock:
            self._tokens = {key: value for key, value in self._tokens.items() if value[1] > now}
            self._tokens[self._digest(token)] = (actor, expires)
        return {
            "access_token": token, "token_type": "Bearer",
            "expires_at": iso(expires), "user": user_summary(user),
        }

    def require_user(self, session: Session, token: str) -> UserSummary:
        key = self._digest(token)
        with self._lock:
            entry = self._tokens.get(key)
            if entry is not None and entry[1] > utcnow():
                return DEMO_USERS[entry[0]]
            self._tokens.pop(key, None)
        raise AppError(401, "UNAUTHENTICATED", "会话已过期或已退出")

    def get_user_summaries(self, session: Session, user_ids: set[str]) -> dict[str, UserSummary]:
        return {user_id: DEMO_USERS[user_id] for user_id in user_ids if user_id in DEMO_USERS}

    def logout(self, token: str) -> None:
        with self._lock:
            entry = self._tokens.pop(self._digest(token), None)
        if entry is None or entry[1] <= utcnow():
            raise AppError(401, "UNAUTHENTICATED", "会话已过期或已退出")


class DemoPost(Base):
    __tablename__ = "team_demo_posts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    post_type: Mapped[str] = mapped_column(String(8), nullable=False)
    title: Mapped[str] = mapped_column(String(60), nullable=False)
    publisher_id: Mapped[str] = mapped_column(String(64), nullable=False)
    category_id: Mapped[str] = mapped_column(String(64), nullable=False)
    category_name: Mapped[str] = mapped_column(String(60), nullable=False)
    campus_id: Mapped[str] = mapped_column(String(64), nullable=False)
    campus_name: Mapped[str] = mapped_column(String(60), nullable=False)
    location_id: Mapped[str] = mapped_column(String(64), nullable=False)
    location_name: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    occurred_at: Mapped[datetime] = mapped_column(POST_TIMESTAMP, nullable=False)
    created_at: Mapped[datetime] = mapped_column(POST_TIMESTAMP, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(POST_TIMESTAMP, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(POST_TIMESTAMP, nullable=True)

    __table_args__ = (Index("ix_team_demo_post_match", "campus_id", "category_id", "post_type", "status"),)


class DemoPostService:
    @staticmethod
    def _post(row: DemoPost) -> Post:
        return Post(
            id=row.id, post_type=row.post_type, title=row.title,
            category=Label(row.category_id, row.category_name),
            campus=Label(row.campus_id, row.campus_name),
            location=Label(row.location_id, row.location_name),
            occurred_at=row.occurred_at, status=row.status, cover_image=None,
            publisher=DEMO_USERS[row.publisher_id],
            created_at=row.created_at, updated_at=row.updated_at,
        )

    @staticmethod
    def _get_row(session: Session, post_id: str, *, lock: bool = False) -> DemoPost | None:
        statement = select(DemoPost).where(DemoPost.id == post_id)
        if lock:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        return session.scalar(statement)

    def get_post_for_claim(self, session: Session, post_id: str, *, lock: bool = False) -> Post | None:
        row = self._get_row(session, post_id, lock=lock)
        return self._post(row) if row is not None else None

    def set_handover_state(self, session: Session, post_id: str, transition: str) -> Post:
        transitions = {
            "reserve": ("open", "in_handover"),
            "complete": ("in_handover", "completed"),
            "reopen": ("in_handover", "open"),
        }
        if transition not in transitions:
            raise ValueError("Unknown handover transition")
        before, after = transitions[transition]
        row = self._get_row(session, post_id, lock=True)
        if row is None:
            raise AppError(404, "NOT_FOUND", "信息不存在")
        if row.status != before:
            raise AppError(409, "STATE_CONFLICT", "信息状态已变化")
        now = to_db(utcnow())
        row.status = after
        row.updated_at = now
        row.completed_at = now if after == "completed" else None
        session.flush()
        return self._post(row)

    def list_match_candidates(self, session: Session, source_post: Post) -> list[Post]:
        opposite = "found" if source_post.post_type == "lost" else "lost"
        rows = session.scalars(select(DemoPost).where(
            DemoPost.post_type == opposite,
            DemoPost.status == "open",
            DemoPost.campus_id == source_post.campus.id,
            DemoPost.category_id == source_post.category.id,
            DemoPost.publisher_id != source_post.publisher.id,
        ))
        return [self._post(row) for row in rows]

    def page(self, session: Session, owner: str | None, page: int, page_size: int) -> tuple[list[Post], int]:
        condition = (
            DemoPost.publisher_id == owner if owner is not None
            else DemoPost.status.in_(("open", "in_handover"))
        )
        total = session.scalar(select(func.count()).select_from(DemoPost).where(condition)) or 0
        offset = (page - 1) * page_size
        if offset >= total:
            return [], total
        rows = session.scalars(
            select(DemoPost).where(condition).order_by(DemoPost.created_at.desc(), DemoPost.id.desc())
            .offset(offset).limit(page_size)
        )
        return [self._post(row) for row in rows], total
