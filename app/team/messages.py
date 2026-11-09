"""Claim-scoped messages for the shared contract."""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import to_db, utcnow
from app.errors import AppError
from app.rules import blocks_contact_info
from app.team.claims import clean_text, get_claim, lock_claim_for_write
from app.team.contracts import PostService, UserSummary
from app.team.models import ClaimMessage


def send_message(session: Session, posts: PostService, actor: UserSummary, claim_id: str, content: str) -> ClaimMessage:
    _, claim, _ = lock_claim_for_write(session, posts, actor, claim_id)
    if claim.status not in {"pending", "accepted"}:
        raise AppError(409, "STATE_CONFLICT", "当前申请仅可查看历史消息")
    content = clean_text(content, "content", 1, 1000)
    if blocks_contact_info(content):
        raise AppError(400, "VALIDATION_ERROR", "消息中请勿填写手机号、邮箱或身份证号码", field="content")

    message = ClaimMessage(
        claim_id=claim.id,
        sender_id=actor.id,
        content=content,
        created_at=to_db(utcnow()),
    )
    session.add(message)
    session.flush()
    return message


def list_messages(
    session: Session,
    actor: UserSummary,
    claim_id: str,
    after_id: str | None,
    limit: int,
) -> tuple[list[ClaimMessage], str | None, bool]:
    get_claim(session, actor, claim_id)
    if not 1 <= limit <= 100:
        raise AppError(400, "VALIDATION_ERROR", "每批消息数应为 1～100", field="limit")

    statement = select(ClaimMessage).where(ClaimMessage.claim_id == claim_id)
    if after_id is not None:
        if not isinstance(after_id, str) or not re.fullmatch(r"[1-9][0-9]{0,9}", after_id):
            raise AppError(400, "VALIDATION_ERROR", "消息游标无效", field="after_id")
        cursor_id = int(after_id)
        if cursor_id > 2_147_483_647:
            raise AppError(400, "VALIDATION_ERROR", "消息游标无效", field="after_id")
        anchor = session.get(ClaimMessage, cursor_id)
        if anchor is None or anchor.claim_id != claim_id:
            raise AppError(400, "VALIDATION_ERROR", "消息游标不属于本会话", field="after_id")
        statement = statement.where(ClaimMessage.id > cursor_id)

    # The Post lock serializes sends in a conversation. The generated IDs therefore advance
    # in conversation order even when messages share a stored timestamp.
    batch = list(session.scalars(statement.order_by(ClaimMessage.id.asc()).limit(limit + 1)))
    has_more = len(batch) > limit
    messages = batch[:limit]
    next_after_id = str(messages[-1].id) if messages else after_id
    return messages, next_after_id, has_more
