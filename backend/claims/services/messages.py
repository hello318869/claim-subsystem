"""Claim-scoped conversation (C, contract §3.8/§6.2).

One claim is one conversation; there is no general chat table.  Message ids increase in
conversation order because sends lock the post row first, which serialises concurrent writes
inside a claim even when two messages share a timestamp.
"""

from __future__ import annotations

import re

from django.utils import timezone

from claims.models import ClaimMessage
from claims.services.claims import clean_text, get_claim, lock_claim_for_write
from common.contracts import UserSummary
from common.errors import AppError
from common.privacy import blocks_contact_info

ACTIVE_STATUSES = frozenset({"pending", "accepted"})
_CURSOR = re.compile(r"[1-9][0-9]{0,9}")
_MAX_CURSOR = 2_147_483_647


def send_message(actor: UserSummary, claim_id: str, content: str) -> ClaimMessage:
    _, claim, _ = lock_claim_for_write(actor, claim_id)
    if claim.status not in ACTIVE_STATUSES:
        raise AppError(409, "STATE_CONFLICT", "当前申请仅可查看历史消息")

    content = clean_text(content, "content", 1, 1000)
    if blocks_contact_info(content):
        raise AppError(
            400,
            "VALIDATION_ERROR",
            "消息中请勿填写手机号、邮箱或身份证号码",
            field="content",
        )

    return ClaimMessage.objects.create(
        claim=claim,
        sender_id=actor.id,
        content=content,
        created_at=timezone.now(),
    )


def list_messages(
    actor: UserSummary,
    claim_id: str,
    after_id: str | None,
    limit: int,
) -> tuple[list[ClaimMessage], str | None, bool]:
    get_claim(actor, claim_id)
    if not 1 <= limit <= 100:
        raise AppError(400, "VALIDATION_ERROR", "每批消息数应为 1～100", field="limit")

    queryset = ClaimMessage.objects.filter(claim_id=claim_id)
    if after_id is not None:
        if not isinstance(after_id, str) or not _CURSOR.fullmatch(after_id):
            raise AppError(400, "VALIDATION_ERROR", "消息游标无效", field="after_id")
        cursor_id = int(after_id)
        if cursor_id > _MAX_CURSOR:
            raise AppError(400, "VALIDATION_ERROR", "消息游标无效", field="after_id")
        if not ClaimMessage.objects.filter(pk=cursor_id, claim_id=claim_id).exists():
            raise AppError(400, "VALIDATION_ERROR", "消息游标不属于本会话", field="after_id")
        queryset = queryset.filter(id__gt=cursor_id)

    batch = list(queryset.order_by("id")[: limit + 1])
    has_more = len(batch) > limit
    messages = batch[:limit]
    next_after_id = str(messages[-1].id) if messages else after_id
    return messages, next_after_id, has_more
