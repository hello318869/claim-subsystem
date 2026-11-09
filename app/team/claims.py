"""Claim transitions in the transaction supplied by the initiating service."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.clock import to_db, utcnow
from app.errors import AppError
from app.team.contracts import Post, PostService, UserSummary
from app.team.models import Claim


ACTIVE_STATUSES = ("pending", "accepted")
CLAIM_STATUSES = frozenset((*ACTIVE_STATUSES, "rejected", "cancelled", "completed", "closed"))
CLOSE_REASONS = frozenset({"post_withdrawn", "another_claim_accepted"})
PUBLIC_POST_STATUSES = frozenset({"open", "in_handover", "completed"})


def clean_text(value: str, field: str, minimum: int, maximum: int) -> str:
    if not isinstance(value, str):
        raise AppError(400, "VALIDATION_ERROR", "请输入文本", field=field)
    value = value.strip()
    if not minimum <= len(value) <= maximum:
        raise AppError(400, "VALIDATION_ERROR", f"文本长度应为 {minimum}～{maximum} 字", field=field)
    return value


def _require_participant(claim: Claim | None, actor: UserSummary) -> Claim:
    if claim is None or actor.id not in (claim.applicant_id, claim.publisher_id):
        raise AppError(404, "NOT_FOUND", "认领申请不存在")
    return claim


def get_claim(session: Session, actor: UserSummary, claim_id: str) -> Claim:
    return _require_participant(session.get(Claim, claim_id), actor)


def _lock_claims(session: Session, post_id: str, *conditions: ColumnElement[bool]) -> list[Claim]:
    statement = (
        select(Claim)
        .where(Claim.post_id == post_id, *conditions)
        .order_by(Claim.id.asc())
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return list(session.scalars(statement))


def lock_claim_for_write(
    session: Session,
    posts: PostService,
    actor: UserSummary,
    claim_id: str,
    *,
    include_active_claims: bool = False,
) -> tuple[Post, Claim, list[Claim]]:
    # The initial read locates the immutable post ID. State checks use the refreshed locked row.
    anchor = get_claim(session, actor, claim_id)
    post = posts.get_post_for_claim(session, anchor.post_id, lock=True)
    if post is None:
        raise AppError(404, "NOT_FOUND", "信息不存在")
    condition: ColumnElement[bool] = Claim.id == claim_id
    if include_active_claims:
        condition = or_(condition, Claim.status.in_(ACTIVE_STATUSES))
    related_claims = _lock_claims(session, anchor.post_id, condition)
    claim = _require_participant(next((row for row in related_claims if row.id == claim_id), None), actor)
    return post, claim, related_claims


def _require_publisher(post: Post, claim: Claim, actor: UserSummary) -> None:
    if actor.id != claim.publisher_id or actor.id != post.publisher.id:
        raise AppError(403, "FORBIDDEN", "只有信息发布者可以审核申请")


def _close_claims(claims: list[Claim], reason: str, now: datetime) -> None:
    for claim in claims:
        claim.status = "closed"
        claim.close_reason = reason
        claim.updated_at = now


def _transition_post(session: Session, posts: PostService, post: Post, transition: str, target: str) -> None:
    # Both modules see their writes through the same transaction, even with autoflush disabled.
    session.flush()
    changed = posts.set_handover_state(session, post.id, transition)
    if changed.id != post.id or changed.status != target:
        raise AppError(409, "STATE_CONFLICT", "信息状态与交接操作不一致")
    session.flush()


def create_claim(
    session: Session,
    posts: PostService,
    actor: UserSummary,
    post_id: str,
    verification_text: str,
) -> Claim:
    if not actor.is_campus_verified:
        raise AppError(403, "IDENTITY_REQUIRED", "请先完成校园身份绑定")
    verification_text = clean_text(verification_text, "verification_text", 10, 1000)
    post = posts.get_post_for_claim(session, post_id, lock=True)
    if post is None or post.status not in PUBLIC_POST_STATUSES:
        raise AppError(404, "NOT_FOUND", "信息不存在")
    if post.post_type not in {"lost", "found"}:
        raise AppError(400, "VALIDATION_ERROR", "此信息类型不能申请认领", field="post_id")
    if actor.id == post.publisher.id:
        raise AppError(403, "FORBIDDEN", "不能申请认领自己发布的信息")

    active = _lock_claims(session, post.id, Claim.status.in_(ACTIVE_STATUSES))
    if any(claim.applicant_id == actor.id for claim in active):
        raise AppError(409, "DUPLICATE_RESOURCE", "您已有该信息的有效认领申请")
    if post.status != "open" or any(claim.status == "accepted" for claim in active):
        raise AppError(409, "STATE_CONFLICT", "该信息当前不能发起认领")

    now = to_db(utcnow())
    claim = Claim(
        id=str(uuid4()),
        post_id=post.id,
        applicant_id=actor.id,
        publisher_id=post.publisher.id,
        verification_text=verification_text,
        status="pending",
        created_at=now,
        updated_at=now,
    )
    session.add(claim)
    session.flush()
    return claim


def list_claims(
    session: Session,
    actor: UserSummary,
    *,
    role: str,
    status: str | None,
    post_id: str | None,
    page: int,
    page_size: int,
) -> tuple[list[Claim], int]:
    if role == "applicant":
        conditions = [Claim.applicant_id == actor.id]
    elif role == "publisher":
        conditions = [Claim.publisher_id == actor.id]
    else:
        raise AppError(400, "VALIDATION_ERROR", "role 应为 applicant 或 publisher", field="role")
    if status is not None:
        if status not in CLAIM_STATUSES:
            raise AppError(400, "VALIDATION_ERROR", "无效的认领状态", field="status")
        conditions.append(Claim.status == status)
    if post_id is not None:
        conditions.append(Claim.post_id == post_id)
    if page < 1:
        raise AppError(400, "VALIDATION_ERROR", "页码至少为 1", field="page")
    if not 1 <= page_size <= 100:
        raise AppError(400, "VALIDATION_ERROR", "每页条数应为 1～100", field="page_size")

    total = session.scalar(select(func.count()).select_from(Claim).where(*conditions)) or 0
    offset = (page - 1) * page_size
    if offset >= total:
        return [], total
    statement = (
        select(Claim)
        .where(*conditions)
        .order_by(Claim.created_at.desc(), Claim.id.desc())
        .offset(offset)
        .limit(page_size)
    )
    return list(session.scalars(statement)), total


def accept_claim(
    session: Session,
    posts: PostService,
    actor: UserSummary,
    claim_id: str,
    decision_note: str | None = None,
) -> Claim:
    post, claim, related = lock_claim_for_write(session, posts, actor, claim_id, include_active_claims=True)
    _require_publisher(post, claim, actor)
    if decision_note is not None:
        decision_note = clean_text(decision_note, "decision_note", 0, 500) or None
    if claim.status == "accepted" and post.status == "in_handover":
        return claim
    if claim.status != "pending" or post.status != "open" or any(row.status == "accepted" for row in related):
        raise AppError(409, "STATE_CONFLICT", "当前状态不允许同意认领")

    now = to_db(utcnow())
    claim.status = "accepted"
    claim.decision_note = decision_note
    claim.updated_at = now
    competing = [row for row in related if row.id != claim.id and row.status == "pending"]
    _close_claims(competing, "another_claim_accepted", now)
    _transition_post(session, posts, post, "reserve", "in_handover")
    return claim


def reject_claim(session: Session, posts: PostService, actor: UserSummary, claim_id: str, decision_note: str) -> Claim:
    post, claim, _ = lock_claim_for_write(session, posts, actor, claim_id)
    _require_publisher(post, claim, actor)
    decision_note = clean_text(decision_note, "decision_note", 1, 500)
    if claim.status == "rejected":
        return claim
    if claim.status != "pending":
        raise AppError(409, "STATE_CONFLICT", "只有待审核申请可以拒绝")

    claim.status = "rejected"
    claim.decision_note = decision_note
    claim.updated_at = to_db(utcnow())
    session.flush()
    return claim


def cancel_claim(session: Session, posts: PostService, actor: UserSummary, claim_id: str) -> Claim:
    post, claim, _ = lock_claim_for_write(session, posts, actor, claim_id)
    if claim.status == "cancelled":
        if claim.cancelled_by_id != actor.id:
            raise AppError(403, "FORBIDDEN", "只有原操作者可以重复取消")
        return claim

    reopen = claim.status == "accepted"
    if claim.status == "pending":
        if claim.applicant_id != actor.id:
            raise AppError(403, "FORBIDDEN", "只有申请者可以取消待审核申请")
    elif reopen:
        if claim.applicant_confirmed_at is not None or claim.publisher_confirmed_at is not None:
            raise AppError(409, "STATE_CONFLICT", "已进入交接确认阶段，无法取消")
        if post.status != "in_handover":
            raise AppError(409, "STATE_CONFLICT", "当前信息不在交接中")
    else:
        raise AppError(409, "STATE_CONFLICT", "当前状态不允许取消认领")

    claim.status = "cancelled"
    claim.cancelled_by_id = actor.id
    claim.updated_at = to_db(utcnow())
    if reopen:
        _transition_post(session, posts, post, "reopen", "open")
    else:
        session.flush()
    return claim


def confirm_handover(session: Session, posts: PostService, actor: UserSummary, claim_id: str) -> Claim:
    post, claim, _ = lock_claim_for_write(session, posts, actor, claim_id)
    if claim.status == "completed":
        return claim
    if claim.status != "accepted" or post.status != "in_handover":
        raise AppError(409, "STATE_CONFLICT", "当前状态不允许确认交接")

    now = to_db(utcnow())
    if actor.id == claim.applicant_id:
        if claim.applicant_confirmed_at is not None:
            return claim
        claim.applicant_confirmed_at = now
    else:
        if claim.publisher_confirmed_at is not None:
            return claim
        claim.publisher_confirmed_at = now
    claim.updated_at = now

    if claim.applicant_confirmed_at is not None and claim.publisher_confirmed_at is not None:
        claim.status = "completed"
        claim.completed_at = now
        _transition_post(session, posts, post, "complete", "completed")
    else:
        session.flush()
    return claim


def close_pending_claims(session: Session, post_id: str, reason: str, except_claim_id: str | None = None) -> int:
    """Close pending claims after the caller has locked the B post in this transaction."""
    if reason not in CLOSE_REASONS:
        raise AppError(400, "VALIDATION_ERROR", "无效的系统关闭原因", field="close_reason")
    conditions = [Claim.status == "pending"]
    if except_claim_id is not None:
        conditions.append(Claim.id != except_claim_id)
    pending = _lock_claims(session, post_id, *conditions)
    _close_claims(pending, reason, to_db(utcnow()))
    session.flush()
    return len(pending)


def has_completed_claim(session: Session, post_id: str) -> bool:
    """Use a locking read after the caller has locked the B post."""
    statement = (
        select(Claim.id)
        .where(Claim.post_id == post_id, Claim.status == "completed")
        .order_by(Claim.id.asc())
        .limit(1)
        .with_for_update()
    )
    return session.scalar(statement) is not None
