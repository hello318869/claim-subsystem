"""Anonymous message repository (never stores an alias or a user id in the row)."""

from __future__ import annotations

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Message


def add(session: Session, message: Message) -> Message:
    session.add(message)
    session.flush()
    return message


def list_after(
    session: Session,
    claim_id: str,
    *,
    after_id: str | None,
    limit: int,
) -> tuple[list[Message], str | None]:
    """Keyset pagination on ``(created_at, id)``.

    Comparing only ``created_at`` drops messages written in the same second, so the cursor is
    the full tuple. A cursor that does not belong to this conversation is rejected instead of
    being silently ignored.
    """
    statement = select(Message).where(Message.claim_id == claim_id)
    if after_id:
        anchor = session.get(Message, after_id)
        if anchor is None or anchor.claim_id != claim_id:
            raise AppError(422, "validation_error", "游标不属于本会话", field="after")
        statement = statement.where(
            or_(
                Message.created_at > anchor.created_at,
                and_(Message.created_at == anchor.created_at, Message.id > anchor.id),
            )
        )
    rows = list(
        session.execute(statement.order_by(Message.created_at, Message.id).limit(limit + 1)).scalars().all()
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_after = rows[-1].id if has_more and rows else None
    return rows, next_after


def count_for_claim(session: Session, claim_id: str) -> int:
    return int(
        session.execute(select(func.count()).select_from(Message).where(Message.claim_id == claim_id)).scalar_one()
    )


def list_all(
    session: Session,
    claim_id: str,
    *,
    page_size: int = 500,
    cap: int = 5000,
) -> tuple[list[Message], int, bool]:
    """Read the whole conversation in pages.

    Returns ``(messages, total, truncated)``. ``truncated`` is True only when the hard cap is
    reached, so an export never silently pretends to be complete.
    """
    collected: list[Message] = []
    cursor: str | None = None
    truncated = False
    while True:
        batch, next_after = list_after(session, claim_id, after_id=cursor, limit=page_size)
        collected.extend(batch)
        if len(collected) >= cap:
            collected = collected[:cap]
            truncated = True
            break
        if next_after is None:
            break
        cursor = next_after
    return collected, count_for_claim(session, claim_id), truncated
