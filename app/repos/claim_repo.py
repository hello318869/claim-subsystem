"""Claim repository.

Lock order is fixed: the caller locks ``listing_snapshots`` first, then calls :func:`lock`.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.models import Claim
from app.state_machine import Status


def get(session: Session, claim_id: str) -> Claim | None:
    return session.get(Claim, claim_id)


def lock(session: Session, claim_id: str) -> Claim | None:
    statement = select(Claim).where(Claim.id == claim_id).with_for_update()
    return session.execute(statement).scalar_one_or_none()


def add(session: Session, claim: Claim) -> Claim:
    session.add(claim)
    session.flush()
    return claim


def page_for_user(
    session: Session,
    *,
    user_id: str,
    role: str,
    page: int,
    page_size: int,
) -> tuple[list[Claim], int]:
    conditions = []
    if role in {"applicant", "all"}:
        conditions.append(Claim.applicant_id == user_id)
    if role in {"finder", "all"}:
        conditions.append(Claim.finder_id == user_id)
    predicate = or_(*conditions)

    total = session.execute(select(func.count()).select_from(Claim).where(predicate)).scalar_one()
    rows = (
        session.execute(
            select(Claim)
            .where(predicate)
            .order_by(Claim.created_at.desc(), Claim.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )
    return list(rows), int(total)


def find_pending_by(session: Session, item_id: str, applicant_id: str) -> Claim | None:
    statement = (
        select(Claim)
        .where(
            Claim.item_id == item_id,
            Claim.applicant_id == applicant_id,
            Claim.status == Status.PENDING.value,
        )
        .order_by(Claim.created_at)
        .limit(1)
    )
    return session.execute(statement).scalars().first()


def pending_for_item(session: Session, item_id: str) -> list[Claim]:
    rows = session.execute(
        select(Claim).where(Claim.item_id == item_id, Claim.status == Status.PENDING.value)
    ).scalars()
    return list(rows)


def close_other_pending(session: Session, item_id: str, keep_claim_id: str, now: datetime) -> int:
    result = session.execute(
        update(Claim)
        .where(
            Claim.item_id == item_id,
            Claim.status == Status.PENDING.value,
            Claim.id != keep_claim_id,
        )
        .values(status=Status.CLOSED_OTHER.value, updated_at=now, decided_at=now)
    )
    return int(result.rowcount or 0)


def expire_due(session: Session, now: datetime, pending_ttl_days: int) -> int:
    changed = session.execute(
        update(Claim)
        .where(Claim.status == Status.PENDING.value, Claim.created_at < now - timedelta(days=pending_ttl_days))
        .values(status=Status.EXPIRED.value, updated_at=now, decided_at=now)
    ).rowcount or 0
    changed += session.execute(
        update(Claim)
        .where(Claim.status == Status.APPROVED.value, Claim.handover_deadline < now)
        .values(status=Status.EXPIRED.value, updated_at=now)
    ).rowcount or 0
    return int(changed)
