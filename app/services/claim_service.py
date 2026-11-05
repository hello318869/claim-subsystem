"""Claim lifecycle service.

Every state-changing method assumes the caller opened a transaction and follows the fixed
lock order: listing row first, then claim row, then handover-code row.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import serializers
from app.clock import from_db, to_db, utcnow
from app.config import Settings
from app.errors import AppError
from app.models import Claim, ItemApproval
from app.repos import audit_repo, claim_repo, code_repo, listing_repo
from app.services.access import membership
from app.services.handover_service import build_handover_row
from app.state_machine import Status


def create(session: Session, settings: Settings, actor: str, payload: dict) -> tuple[int, dict]:
    now = utcnow()
    item = listing_repo.lock(session, payload["item_id"])
    if item is None:
        raise AppError(404, "not_found", "招领记录不存在")
    if item.kind != "found":
        raise AppError(422, "not_claimable", "只有拾获记录可以被认领")
    if item.status != "published":
        raise AppError(422, "not_claimable", "该记录当前不是可认领状态")
    if item.publisher_user_id == actor:
        raise AppError(422, "not_claimable", "不能认领自己发布的记录")
    if listing_repo.approved_claim_id(session, item.item_id, for_update=True):
        raise AppError(409, "already_approved", "该记录已有获批的认领申请")

    duplicate = claim_repo.find_pending_by(session, item.item_id, actor, for_update=True)
    if duplicate is not None:
        return 200, serializers.claim_dto(duplicate, actor)

    claim = Claim(
        id=str(uuid.uuid4()),
        item_id=item.item_id,
        applicant_id=actor,
        finder_id=item.publisher_user_id,
        status=Status.PENDING.value,
        evidence_text=payload["evidence_text"],
        item_number=payload.get("item_number") or None,
        created_at=to_db(now),
        updated_at=to_db(now),
    )
    claim_repo.add(session, claim)
    audit_repo.add(
        session,
        actor_id=actor,
        action="claim.create",
        claim_id=claim.id,
        item_id=item.item_id,
        detail="created",
        now=to_db(now),
    )
    return 201, serializers.claim_dto(claim, actor)


def _locked_claim(session: Session, actor: str, claim_id: str) -> tuple[Claim, object]:
    anchor = claim_repo.get(session, claim_id)
    if anchor is None:
        raise AppError(404, "not_found", "认领申请不存在")
    item = listing_repo.lock(session, anchor.item_id)
    claim = claim_repo.lock(session, claim_id)
    if claim is None:
        raise AppError(404, "not_found", "认领申请不存在")
    membership(claim, actor)
    return claim, item


def approve(session: Session, settings: Settings, actor: str, claim_id: str) -> dict:
    now = utcnow()
    claim, item = _locked_claim(session, actor, claim_id)
    if claim.finder_id != actor:
        raise AppError(403, "forbidden", "只有拾获方可以批准")
    if claim.status != Status.PENDING.value:
        raise AppError(409, "invalid_transition", "只有待核验的申请可以批准")
    if item is None:
        raise AppError(404, "not_found", "招领记录不存在")
    if listing_repo.approved_claim_id(session, claim.item_id, for_update=True) is not None:
        raise AppError(409, "already_approved", "该记录已有获批的认领申请")
    try:
        session.add(
            ItemApproval(item_id=claim.item_id, claim_id=claim.id, approved_at=to_db(now))
        )
        session.flush()
    except IntegrityError as exc:
        raise AppError(409, "already_approved", "并发批准冲突：该记录已被其他申请占用") from exc

    claim.status = Status.APPROVED.value
    claim.decided_at = to_db(now)
    claim.approved_at = to_db(now)
    claim.handover_deadline = to_db(now + timedelta(hours=settings.handover_deadline_hours))
    claim.updated_at = to_db(now)
    session.flush()

    claim_repo.close_other_pending(session, claim.item_id, claim.id, to_db(now))
    code_repo.add(session, build_handover_row(settings, claim, now))
    audit_repo.add(
        session,
        actor_id=actor,
        action="claim.approve",
        claim_id=claim.id,
        item_id=claim.item_id,
        detail="approved",
        now=to_db(now),
    )
    return serializers.claim_dto(claim, actor, code_repo.get(session, claim.id))


def reject(session: Session, actor: str, claim_id: str, reason: str) -> dict:
    now = utcnow()
    claim, _ = _locked_claim(session, actor, claim_id)
    if claim.finder_id != actor:
        raise AppError(403, "forbidden", "只有拾获方可以驳回")
    if claim.status != Status.PENDING.value:
        raise AppError(409, "invalid_transition", "只有待核验的申请可以驳回")
    claim.status = Status.REJECTED.value
    claim.reason = reason
    claim.decided_at = to_db(now)
    claim.updated_at = to_db(now)
    audit_repo.add(
        session,
        actor_id=actor,
        action="claim.reject",
        claim_id=claim.id,
        item_id=claim.item_id,
        detail="rejected",
        now=to_db(now),
    )
    return serializers.claim_dto(claim, actor)


def withdraw(session: Session, actor: str, claim_id: str) -> dict:
    now = utcnow()
    claim, _ = _locked_claim(session, actor, claim_id)
    if claim.applicant_id != actor:
        raise AppError(403, "forbidden", "只有申请人可以撤销")
    if claim.status != Status.PENDING.value:
        raise AppError(409, "invalid_transition", "只有待核验的申请可以撤销")
    claim.status = Status.WITHDRAWN.value
    claim.decided_at = to_db(now)
    claim.updated_at = to_db(now)
    audit_repo.add(
        session,
        actor_id=actor,
        action="claim.withdraw",
        claim_id=claim.id,
        item_id=claim.item_id,
        detail="withdrawn",
        now=to_db(now),
    )
    return serializers.claim_dto(claim, actor)


def dispute(session: Session, actor: str, claim_id: str, reason: str) -> dict:
    now = utcnow()
    claim, _ = _locked_claim(session, actor, claim_id)
    if claim.status != Status.APPROVED.value:
        raise AppError(409, "invalid_transition", "只有已批准的申请可以标记争议")
    claim.status = Status.DISPUTED.value
    claim.reason = reason
    claim.updated_at = to_db(now)
    audit_repo.add(
        session,
        actor_id=actor,
        action="claim.dispute",
        claim_id=claim.id,
        item_id=claim.item_id,
        detail="disputed",
        now=to_db(now),
    )
    return serializers.claim_dto(claim, actor, code_repo.get(session, claim.id))


def get_detail(session: Session, settings: Settings, actor: str, claim_id: str) -> dict:
    claim = claim_repo.get(session, claim_id)
    if claim is None:
        raise AppError(404, "not_found", "认领申请不存在")
    membership(claim, actor)
    now = utcnow()
    deadline = from_db(claim.handover_deadline)
    if claim.status == Status.APPROVED.value and deadline is not None and now >= deadline:
        claim.status = Status.EXPIRED.value
        claim.updated_at = to_db(now)
        session.commit()
    return serializers.claim_dto(claim, actor, code_repo.get(session, claim.id))


def list_claims(
    session: Session,
    settings: Settings,
    actor: str,
    *,
    role: str,
    page: int,
    page_size: int,
) -> dict:
    claim_repo.expire_due(session, to_db(utcnow()), settings.pending_ttl_days)
    session.commit()
    rows, total = claim_repo.page_for_user(session, user_id=actor, role=role, page=page, page_size=page_size)
    items = [serializers.claim_dto(row, actor, code_repo.get(session, row.id)) for row in rows]
    return serializers.page_dto(items, total, page, page_size)


def dispute_export(session: Session, actor: str, claim_id: str) -> dict:
    from app.repos import message_repo

    claim = claim_repo.get(session, claim_id)
    if claim is None:
        raise AppError(404, "not_found", "认领申请不存在")
    membership(claim, actor)
    item = listing_repo.get(session, claim.item_id)
    messages, message_total, messages_truncated = message_repo.list_all(session, claim.id)
    timeline = [
        {
            "at": serializers.iso(event.created_at),
            "event": event.action,
            "actor_alias": serializers.alias_for(claim.id, "applicant" if event.actor_id == claim.applicant_id else "finder"),
        }
        for event in audit_repo.list_for_claim(session, claim.id)
    ]
    return {
        "claim_id": claim.id,
        "exported_at": serializers.iso(utcnow()),
        "state": claim.status,
        "item": serializers.public_listing(item) if item else None,
        "timeline": timeline,
        "evidence_text": claim.evidence_text,
        "item_number": claim.item_number,
        "dispute_reason": claim.reason,
        "messages_total": message_total,
        "messages_truncated": messages_truncated,
        "messages": [
            {
                "sender_alias": serializers.alias_for(claim.id, message.sender_role),
                "text": message.body,
                "created_at": serializers.iso(message.created_at),
            }
            for message in messages
        ],
    }
