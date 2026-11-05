"""Handover-code row repository."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import HandoverCode


def get(session: Session, claim_id: str) -> HandoverCode | None:
    return session.get(HandoverCode, claim_id)


def lock(session: Session, claim_id: str) -> HandoverCode | None:
    statement = select(HandoverCode).where(HandoverCode.claim_id == claim_id).with_for_update()
    return session.execute(statement).scalar_one_or_none()


def add(session: Session, row: HandoverCode) -> HandoverCode:
    session.add(row)
    session.flush()
    return row
