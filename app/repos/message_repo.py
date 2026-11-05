"""Anonymous message repository (never stores an alias or a user id in the row)."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

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
    statement = select(Message).where(Message.claim_id == claim_id)
    if after_id:
        anchor = session.get(Message, after_id)
        if anchor is not None and anchor.claim_id == claim_id:
            statement = statement.where(Message.created_at > anchor.created_at)
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
