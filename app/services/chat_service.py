"""Anonymous conversation service with server-side contact-info filtering."""

from __future__ import annotations

import time
import uuid
from collections import defaultdict, deque

from sqlalchemy.orm import Session

from app import serializers
from app.clock import to_db, utcnow
from app.config import Settings
from app.errors import AppError
from app.models import Claim, Message
from app.repos import claim_repo, message_repo
from app.services.access import membership
from app.state_machine import Status

_buckets: dict[tuple[str, str], deque[float]] = defaultdict(deque)
CHAT_OPEN_STATES = {Status.PENDING.value, Status.APPROVED.value, Status.DISPUTED.value}


def _rate_limit(claim_id: str, actor: str, limit_per_minute: int) -> None:
    now = time.monotonic()
    bucket = _buckets[(claim_id, actor)]
    while bucket and now - bucket[0] > 60:
        bucket.popleft()
    if len(bucket) >= limit_per_minute:
        raise AppError(429, "rate_limited", "消息发送过于频繁，请稍后再试", retry_after_seconds=60)
    bucket.append(now)


def _member_claim(session: Session, actor: str, claim_id: str) -> tuple[Claim, str]:
    claim = claim_repo.get(session, claim_id)
    if claim is None:
        raise AppError(404, "not_found", "认领申请不存在")
    return claim, membership(claim, actor)


def list_messages(
    session: Session,
    actor: str,
    claim_id: str,
    *,
    after: str | None,
    limit: int,
) -> dict:
    claim, _ = _member_claim(session, actor, claim_id)
    rows, next_after = message_repo.list_after(session, claim.id, after_id=after, limit=limit)
    return {
        "items": [serializers.message_dto(row, claim, actor) for row in rows],
        "next_after": next_after,
    }


def send_message(
    session: Session,
    settings: Settings,
    actor: str,
    claim_id: str,
    text: str,
) -> dict:
    from app.rules import scan_contact_info

    claim, role = _member_claim(session, actor, claim_id)
    if claim.status not in CHAT_OPEN_STATES:
        raise AppError(409, "invalid_transition", "该申请当前不接受新消息")
    _rate_limit(claim.id, actor, settings.chat_rate_limit_per_minute)

    hits = scan_contact_info(text)
    if hits:
        raise AppError(
            422,
            "contact_info_blocked",
            "消息中可能包含手机号、邮箱或证件号，已按隐私规则拦截；请改用私有核验字段提交，避免误伤物品编号",
            field="text",
        )

    now = utcnow()
    message = Message(
        id=str(uuid.uuid4()),
        claim_id=claim.id,
        sender_role=role,
        body=text.strip(),
        created_at=to_db(now),
    )
    message_repo.add(session, message)
    return serializers.message_dto(message, claim, actor)
