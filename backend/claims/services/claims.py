"""Claim transitions (C), always inside the caller's transaction.

Contract §7.1/§7.2 rules encoded here:

* a post is locked first, then its claims ordered by id (deadlock avoidance, §7.3);
* ``accept`` selects exactly one handover partner, closes competing pending claims and puts the
  post ``in_handover`` in one transaction;
* a single confirmation only records that party's timestamp; only two confirmations complete
  both the claim and the post;
* repeated operations that already reached their target state return the current object, while
  a different current state is ``409 STATE_CONFLICT``.
"""

from __future__ import annotations

from uuid import uuid4

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from claims.models import Claim
from common.contracts import Post as PostRecord
from common.contracts import UserSummary
from common.errors import AppError
from common.serializers import clean_text
from posts import services as post_service

ACTIVE_STATUSES = ("pending", "accepted")
CLAIM_STATUSES = frozenset((*ACTIVE_STATUSES, "rejected", "cancelled", "completed", "closed"))
CLOSE_REASONS = frozenset({"post_withdrawn", "another_claim_accepted"})
PUBLIC_POST_STATUSES = frozenset({"open", "in_handover", "completed"})


def require_participant(claim: Claim | None, actor: UserSummary) -> Claim:
    if claim is None or actor.id not in (claim.applicant_id, claim.publisher_id):
        raise AppError(404, "NOT_FOUND", "认领申请不存在")
    return claim


def get_claim(actor: UserSummary, claim_id: str) -> Claim:
    return require_participant(Claim.objects.filter(pk=claim_id).first(), actor)


def _lock_claims(post_id: str, *conditions: Q) -> list[Claim]:
    return list(
        Claim.objects.select_for_update().filter(*conditions, post_id=post_id).order_by("id")
    )


def lock_claim_for_write(
    actor: UserSummary,
    claim_id: str,
    *,
    include_active_claims: bool = False,
) -> tuple[PostRecord, Claim, list[Claim]]:
    """Lock the post, then the claims, and return the current (refreshed) rows."""
    anchor = get_claim(actor, claim_id)
    post = post_service.get_post_for_claim(anchor.post_id, lock=True)
    if post is None:
        raise AppError(404, "NOT_FOUND", "信息不存在")

    condition = Q(id=claim_id)
    if include_active_claims:
        condition |= Q(status__in=ACTIVE_STATUSES)
    related = _lock_claims(anchor.post_id, condition)
    claim = require_participant(next((row for row in related if row.id == claim_id), None), actor)
    return post, claim, related


def _require_publisher(post: PostRecord, claim: Claim, actor: UserSummary) -> None:
    if actor.id != claim.publisher_id or actor.id != post.publisher.id:
        raise AppError(403, "FORBIDDEN", "只有信息发布者可以审核申请")


def _close_claims(claims: list[Claim], reason: str, now) -> None:
    for claim in claims:
        claim.status = "closed"
        claim.close_reason = reason
        claim.updated_at = now
        claim.active_key = None
    if claims:
        Claim.objects.bulk_update(
            claims, ["status", "close_reason", "updated_at", "active_key"]
        )


def _transition_post(post: PostRecord, transition: str, target: str) -> None:
    changed = post_service.set_handover_state(post.id, transition)
    if changed.id != post.id or changed.status != target:
        raise AppError(409, "STATE_CONFLICT", "信息状态与交接操作不一致")


def create_claim(actor: UserSummary, post_id: str, verification_text: str) -> Claim:
    if not actor.is_campus_verified:
        raise AppError(403, "IDENTITY_REQUIRED", "请先完成校园身份绑定")
    verification_text = clean_text(verification_text, "verification_text", 10, 1000)

    post = post_service.get_post_for_claim(post_id, lock=True)
    if post is None or post.status not in PUBLIC_POST_STATUSES:
        raise AppError(404, "NOT_FOUND", "信息不存在")
    if post.post_type not in {"lost", "found"}:
        raise AppError(400, "VALIDATION_ERROR", "此信息类型不能申请认领", field="post_id")
    if actor.id == post.publisher.id:
        raise AppError(403, "FORBIDDEN", "不能申请认领自己发布的信息")

    active = _lock_claims(post.id, Q(status__in=ACTIVE_STATUSES))
    if any(row.applicant_id == actor.id for row in active):
        raise AppError(409, "DUPLICATE_RESOURCE", "您已有该信息的有效认领申请")
    if post.status != "open" or any(row.status == "accepted" for row in active):
        raise AppError(409, "STATE_CONFLICT", "该信息当前不能发起认领")

    now = timezone.now()
    claim = Claim(
        id=str(uuid4()),
        post_id=post.id,
        applicant_id=actor.id,
        publisher_id=post.publisher.id,
        verification_text=verification_text,
        status="pending",
        active_key=f"{post.id}:{actor.id}",
        created_at=now,
        updated_at=now,
    )
    try:
        with transaction.atomic():
            claim.save()
    except IntegrityError as exc:  # last line of defence for concurrent duplicates
        raise AppError(409, "DUPLICATE_RESOURCE", "您已有该信息的有效认领申请") from exc
    return claim


def list_claims(
    actor: UserSummary,
    *,
    role: str,
    status: str | None,
    post_id: str | None,
    page: int,
    page_size: int,
) -> tuple[list[Claim], int]:
    if role == "applicant":
        conditions = Q(applicant_id=actor.id)
    elif role == "publisher":
        conditions = Q(publisher_id=actor.id)
    else:
        raise AppError(400, "VALIDATION_ERROR", "role 应为 applicant 或 publisher", field="role")
    if status is not None:
        if status not in CLAIM_STATUSES:
            raise AppError(400, "VALIDATION_ERROR", "无效的认领状态", field="status")
        conditions &= Q(status=status)
    if post_id is not None:
        conditions &= Q(post_id=post_id)
    if page < 1:
        raise AppError(400, "VALIDATION_ERROR", "页码至少为 1", field="page")
    if not 1 <= page_size <= 100:
        raise AppError(400, "VALIDATION_ERROR", "每页条数应为 1～100", field="page_size")

    queryset = Claim.objects.filter(conditions)
    total = queryset.count()
    offset = (page - 1) * page_size
    if offset >= total:
        return [], total
    return list(queryset.order_by("-created_at", "-id")[offset : offset + page_size]), total


def accept_claim(
    actor: UserSummary, claim_id: str, decision_note: str | None = None
) -> Claim:
    post, claim, related = lock_claim_for_write(actor, claim_id, include_active_claims=True)
    _require_publisher(post, claim, actor)

    if decision_note is not None:
        decision_note = decision_note.strip()
        if not 0 <= len(decision_note) <= 500:
            raise AppError(400, "VALIDATION_ERROR", "文本长度应为 0～500 字", field="decision_note")
        decision_note = decision_note or None

    if claim.status == "accepted" and post.status == "in_handover":
        return claim
    if (
        claim.status != "pending"
        or post.status != "open"
        or any(row.status == "accepted" for row in related)
    ):
        raise AppError(409, "STATE_CONFLICT", "当前状态不允许同意认领")

    now = timezone.now()
    competing = [row for row in related if row.id != claim.id and row.status == "pending"]
    _close_claims(competing, "another_claim_accepted", now)

    claim.status = "accepted"
    claim.decision_note = decision_note
    claim.accepted_key = post.id
    claim.updated_at = now
    try:
        with transaction.atomic():
            claim.save(
                update_fields=["status", "decision_note", "accepted_key", "updated_at"]
            )
    except IntegrityError as exc:
        raise AppError(409, "STATE_CONFLICT", "该信息已选择其他认领申请") from exc

    _transition_post(post, "reserve", "in_handover")
    return claim


def reject_claim(actor: UserSummary, claim_id: str, decision_note: str) -> Claim:
    post, claim, _ = lock_claim_for_write(actor, claim_id)
    _require_publisher(post, claim, actor)
    decision_note = clean_text(decision_note, "decision_note", 1, 500)

    if claim.status == "rejected":
        return claim
    if claim.status != "pending":
        raise AppError(409, "STATE_CONFLICT", "只有待审核申请可以拒绝")

    claim.status = "rejected"
    claim.decision_note = decision_note
    claim.active_key = None
    claim.updated_at = timezone.now()
    claim.save(update_fields=["status", "decision_note", "active_key", "updated_at"])
    return claim


def cancel_claim(actor: UserSummary, claim_id: str) -> Claim:
    post, claim, _ = lock_claim_for_write(actor, claim_id)

    if claim.status == "cancelled":
        if claim.cancelled_by_id != actor.id:
            raise AppError(403, "FORBIDDEN", "只有原操作者可以重复取消")
        return claim

    reopen = claim.status == "accepted"
    if claim.status == "pending":
        if claim.applicant_id != actor.id:
            raise AppError(403, "FORBIDDEN", "只有申请者可以取消待审核申请")
    elif reopen:
        if (
            claim.applicant_confirmed_at is not None
            or claim.publisher_confirmed_at is not None
        ):
            raise AppError(409, "STATE_CONFLICT", "已进入交接确认阶段，无法取消")
        if post.status != "in_handover":
            raise AppError(409, "STATE_CONFLICT", "当前信息不在交接中")
    else:
        raise AppError(409, "STATE_CONFLICT", "当前状态不允许取消认领")

    claim.status = "cancelled"
    claim.cancelled_by_id = actor.id
    claim.active_key = None
    claim.accepted_key = None
    claim.updated_at = timezone.now()
    claim.save(
        update_fields=[
            "status",
            "cancelled_by_id",
            "active_key",
            "accepted_key",
            "updated_at",
        ]
    )
    if reopen:
        _transition_post(post, "reopen", "open")
    return claim


def confirm_handover(actor: UserSummary, claim_id: str) -> Claim:
    post, claim, _ = lock_claim_for_write(actor, claim_id)

    if claim.status == "completed":
        return claim
    if claim.status != "accepted" or post.status != "in_handover":
        raise AppError(409, "STATE_CONFLICT", "当前状态不允许确认交接")

    now = timezone.now()
    if actor.id == claim.applicant_id:
        if claim.applicant_confirmed_at is not None:
            return claim
        claim.applicant_confirmed_at = now
    else:
        if claim.publisher_confirmed_at is not None:
            return claim
        claim.publisher_confirmed_at = now
    claim.updated_at = now

    both_confirmed = (
        claim.applicant_confirmed_at is not None and claim.publisher_confirmed_at is not None
    )
    if both_confirmed:
        claim.status = "completed"
        claim.completed_at = now
        claim.active_key = None
        claim.save(
            update_fields=[
                "applicant_confirmed_at",
                "publisher_confirmed_at",
                "status",
                "completed_at",
                "active_key",
                "updated_at",
            ]
        )
        _transition_post(post, "complete", "completed")
    else:
        claim.save(
            update_fields=["applicant_confirmed_at", "publisher_confirmed_at", "updated_at"]
        )
    return claim


def close_pending_claims(
    post_id: str, reason: str, except_claim_id: str | None = None
) -> int:
    """Internal function for B (§7.3); the caller has already locked the post."""
    if reason not in CLOSE_REASONS:
        raise AppError(400, "VALIDATION_ERROR", "无效的系统关闭原因", field="close_reason")
    conditions = [Q(status="pending")]
    if except_claim_id is not None:
        conditions.append(~Q(id=except_claim_id))
    pending = _lock_claims(post_id, *conditions)
    _close_claims(pending, reason, timezone.now())
    return len(pending)


def has_completed_claim(post_id: str) -> bool:
    """Internal function for B's ``reopen`` check (§7.3)."""
    return (
        Claim.objects.select_for_update()
        .filter(post_id=post_id, status="completed")
        .order_by("id")
        .values_list("id", flat=True)
        .first()
        is not None
    )
