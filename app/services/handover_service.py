"""Two-party handover: fetch own code, submit the counterpart's code, explicit reset.

Persistable failure paths (wrong code, deadline elapsed) return ``(status, body)`` so the
router commits the attempt counters; pure rejections raise ``AppError`` and roll back.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app import serializers
from app.clock import from_db, to_db, utcnow
from app.config import Settings
from app.errors import AppError, error_body
from app.handover import code_expiry, derive_code, digest_matches, keyed_digest, new_nonce
from app.models import Claim, HandoverCode
from app.repos import audit_repo, claim_repo, code_repo, listing_repo
from app.services.access import counterpart, membership
from app.state_machine import Status


def build_handover_row(settings: Settings, claim: Claim, now: datetime, *, resets: int = 0) -> HandoverCode:
    """Create a fresh code row. ``expires`` is truncated to whole seconds so the derived code
    survives a database round trip unchanged."""
    nonce = new_nonce()
    deadline = from_db(claim.handover_deadline)
    expires = code_expiry(now, settings.code_ttl_minutes, deadline).replace(microsecond=0)
    epoch = int(expires.timestamp())
    return HandoverCode(
        claim_id=claim.id,
        nonce=nonce,
        digest_applicant=keyed_digest(
            settings.handover_secret, derive_code(settings.handover_secret, claim.id, "applicant", nonce, epoch)
        ),
        digest_finder=keyed_digest(
            settings.handover_secret, derive_code(settings.handover_secret, claim.id, "finder", nonce, epoch)
        ),
        expires_at=to_db(expires),
        attempts_applicant=0,
        attempts_finder=0,
        cooldown_until_applicant=None,
        cooldown_until_finder=None,
        cooldown_triggered_applicant=False,
        cooldown_triggered_finder=False,
        confirmed_applicant=False,
        confirmed_finder=False,
        reset_count=resets,
        issued_at=to_db(now),
        updated_at=to_db(now),
    )


def _lock_pair(session: Session, claim_id: str) -> Claim:
    anchor = claim_repo.get(session, claim_id)
    if anchor is None:
        raise AppError(404, "not_found", "认领申请不存在")
    listing_repo.lock(session, anchor.item_id)
    claim = claim_repo.lock(session, claim_id)
    if claim is None:
        raise AppError(404, "not_found", "认领申请不存在")
    return claim


def _cooldown_seconds(row: HandoverCode, role: str, now: datetime) -> int:
    until = from_db(getattr(row, f"cooldown_until_{role}"))
    if until is None or now >= until:
        return 0
    return max(1, math.ceil((until - now).total_seconds()))


def get_code(session: Session, settings: Settings, actor: str, claim_id: str) -> dict:
    claim = claim_repo.get(session, claim_id)
    if claim is None:
        raise AppError(404, "not_found", "认领申请不存在")
    role = membership(claim, actor)
    if claim.status != Status.APPROVED.value:
        raise AppError(409, "invalid_transition", "只有已批准的申请才有交接码")
    now = utcnow()
    row = code_repo.get(session, claim.id)
    if row is None:
        raise AppError(409, "conflict", "交接码尚未生成")
    expires = from_db(row.expires_at)
    if expires is None or now >= expires:
        raise AppError(410, "code_expired", "交接码已过期，请申请重置")
    waiting = _cooldown_seconds(row, role, now)
    if waiting:
        raise AppError(429, "cooldown_active", "交接码错误次数过多，请稍后再试", retry_after_seconds=waiting)
    code = derive_code(settings.handover_secret, claim.id, role, row.nonce, int(expires.timestamp()))
    return {"claim_id": claim.id, "code": code, "expires_at": serializers.iso(row.expires_at)}


def confirm(session: Session, settings: Settings, actor: str, claim_id: str, submitted: str) -> tuple[int, dict]:
    now = utcnow()
    claim = _lock_pair(session, claim_id)
    role = membership(claim, actor)
    other = counterpart(role)

    if claim.status == Status.COMPLETED.value:
        return 200, serializers.claim_dto(claim, actor, code_repo.get(session, claim.id))
    if claim.status != Status.APPROVED.value:
        raise AppError(409, "invalid_transition", "申请不在可交接状态")

    deadline = from_db(claim.handover_deadline)
    if deadline is not None and now >= deadline:
        claim.status = Status.EXPIRED.value
        claim.updated_at = to_db(now)
        return 410, error_body("code_expired", "交接期限已过，申请已失效")

    row = code_repo.lock(session, claim.id)
    if row is None:
        raise AppError(409, "conflict", "交接码尚未生成")
    expires = from_db(row.expires_at)
    if expires is None or now >= expires:
        return 410, error_body("code_expired", "交接码已过期，请申请重置")

    waiting = _cooldown_seconds(row, role, now)
    if waiting:
        raise AppError(429, "cooldown_active", "交接码错误次数过多，请稍后再试", retry_after_seconds=waiting)

    if getattr(row, f"confirmed_{role}"):
        if row.confirmed_applicant and row.confirmed_finder:
            claim.status = Status.COMPLETED.value
            claim.completed_at = claim.completed_at or to_db(now)
            claim.updated_at = to_db(now)
        return 200, serializers.claim_dto(claim, actor, row)

    expected = getattr(row, f"digest_{other}")
    if digest_matches(expected, submitted.strip(), settings.handover_secret):
        setattr(row, f"confirmed_{role}", True)
        setattr(row, f"attempts_{role}", 0)
        row.updated_at = to_db(now)
        if row.confirmed_applicant and row.confirmed_finder:
            claim.status = Status.COMPLETED.value
            claim.completed_at = to_db(now)
            claim.updated_at = to_db(now)
            audit_repo.add(
                session,
                actor_id=actor,
                action="handover.complete",
                claim_id=claim.id,
                item_id=claim.item_id,
                detail="completed",
                now=to_db(now),
            )
        session.flush()
        return 200, serializers.claim_dto(claim, actor, row)

    attempts = int(getattr(row, f"attempts_{role}")) + 1
    if attempts >= settings.max_attempts:
        setattr(row, f"attempts_{role}", 0)
        setattr(row, f"cooldown_until_{role}", to_db(now + timedelta(seconds=settings.cooldown_seconds)))
        setattr(row, f"cooldown_triggered_{role}", True)
    else:
        setattr(row, f"attempts_{role}", attempts)
    row.updated_at = to_db(now)
    audit_repo.add(
        session,
        actor_id=actor,
        action="handover.failed",
        claim_id=claim.id,
        item_id=claim.item_id,
        detail=f"attempt={attempts}",
        now=to_db(now),
    )
    remaining = max(0, settings.max_attempts - attempts)
    return 422, error_body("invalid_code", f"交接码不正确，剩余尝试 {remaining} 次", "code")


def reset(session: Session, settings: Settings, actor: str, claim_id: str, reason: str) -> tuple[int, dict]:
    now = utcnow()
    claim = _lock_pair(session, claim_id)
    role = membership(claim, actor)
    if claim.status != Status.APPROVED.value:
        raise AppError(409, "invalid_transition", "只有已批准的申请可以重置交接码")

    row = code_repo.lock(session, claim.id)
    if row is None:
        raise AppError(409, "conflict", "交接码尚未生成")

    deadline = from_db(claim.handover_deadline)
    if deadline is not None and now >= deadline:
        # Persist the terminal state: returning (instead of raising) keeps the transaction
        # commit that the router performs, so EXPIRED is not rolled back.
        claim.status = Status.EXPIRED.value
        claim.updated_at = to_db(now)
        session.flush()
        return 410, error_body("code_expired", "交接期限已过，申请已失效")

    if row.reset_count >= settings.max_resets:
        raise AppError(409, "reset_not_allowed", f"最多重置 {settings.max_resets} 次")

    expires = from_db(row.expires_at) or now
    triggered = bool(getattr(row, f"cooldown_triggered_{role}"))
    cooldown_until = from_db(getattr(row, f"cooldown_until_{role}"))
    allowed = (triggered and cooldown_until is not None and now >= cooldown_until) or now >= expires
    if not allowed:
        raise AppError(409, "reset_not_allowed", "码仍有效且未触发冷却，不能重置")

    fresh = build_handover_row(settings, claim, now, resets=row.reset_count + 1)
    row.nonce = fresh.nonce
    row.digest_applicant = fresh.digest_applicant
    row.digest_finder = fresh.digest_finder
    row.expires_at = fresh.expires_at
    row.attempts_applicant = 0
    row.attempts_finder = 0
    row.cooldown_until_applicant = None
    row.cooldown_until_finder = None
    row.cooldown_triggered_applicant = False
    row.cooldown_triggered_finder = False
    row.confirmed_applicant = False
    row.confirmed_finder = False
    row.reset_count = fresh.reset_count
    row.issued_at = to_db(now)
    row.updated_at = to_db(now)
    audit_repo.add(
        session,
        actor_id=actor,
        action="handover.reset",
        claim_id=claim.id,
        item_id=claim.item_id,
        detail=f"reset={row.reset_count}",
        now=to_db(now),
    )
    return 200, {
        "claim_id": claim.id,
        "expires_at": serializers.iso(row.expires_at),
        "reset_count": row.reset_count,
        "counterparty_must_refetch": True,
        "reason": reason,
    }
