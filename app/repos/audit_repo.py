"""Append-only audit trail. Detail strings never contain codes or identity mappings."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditEvent


def add(
    session: Session,
    *,
    actor_id: str,
    action: str,
    claim_id: str | None,
    item_id: str | None,
    detail: str | None,
    now,
) -> AuditEvent:
    event = AuditEvent(
        actor_id=actor_id,
        action=action,
        claim_id=claim_id,
        item_id=item_id,
        detail=detail,
        created_at=now,
    )
    session.add(event)
    session.flush()
    return event


def list_for_claim(session: Session, claim_id: str) -> list[AuditEvent]:
    return list(
        session.execute(
            select(AuditEvent).where(AuditEvent.claim_id == claim_id).order_by(AuditEvent.id)
        )
        .scalars()
        .all()
    )
