"""Response builders for ``ClaimView`` / ``MessageView`` (contract §3.9).

Related records are batched so a 100-item page costs a constant number of queries rather than
one post query per claim.
"""

from __future__ import annotations

from claims.models import Claim, ClaimMessage
from common.clock import iso
from common.contracts import UserSummary, user_summary
from common.errors import AppError
from identity import services as identity_services
from posts import services as post_service


def claim_views(records: list[Claim], *, lock: bool = False) -> list[dict]:
    if not records:
        return []

    user_ids = {record.applicant_id for record in records}
    user_ids |= {record.publisher_id for record in records}
    users = identity_services.get_user_summaries(user_ids)
    posts = post_service.get_posts_for_claims(
        {record.post_id for record in records}, lock=lock
    )

    result: list[dict] = []
    for record in records:
        post = posts.get(record.post_id)
        applicant: UserSummary | None = users.get(record.applicant_id)
        publisher: UserSummary | None = users.get(record.publisher_id)
        if post is None or applicant is None or publisher is None:
            raise AppError(500, "INTERNAL_ERROR", "关联信息不可用")
        result.append(
            {
                "id": record.id,
                "post_id": record.post_id,
                "applicant_id": record.applicant_id,
                "verification_text": record.verification_text,
                "status": record.status,
                "decision_note": record.decision_note,
                "close_reason": record.close_reason,
                "applicant_confirmed_at": iso(record.applicant_confirmed_at),
                "publisher_confirmed_at": iso(record.publisher_confirmed_at),
                "created_at": iso(record.created_at),
                "updated_at": iso(record.updated_at),
                "applicant": user_summary(applicant),
                "publisher": user_summary(publisher),
                # A short record that survives withdrawal; it grants no extra read permission.
                "post": {
                    "id": post.id,
                    "title": post.title,
                    "post_type": post.post_type,
                    "status": post.status,
                },
            }
        )
    return result


def claim_view(record: Claim, *, lock: bool = False) -> dict:
    return claim_views([record], lock=lock)[0]


def message_views(records: list[ClaimMessage]) -> list[dict]:
    if not records:
        return []
    users = identity_services.get_user_summaries({record.sender_id for record in records})
    result: list[dict] = []
    for record in records:
        sender = users.get(record.sender_id)
        if sender is None:
            raise AppError(500, "INTERNAL_ERROR", "关联用户不可用")
        result.append(
            {
                "id": str(record.id),
                "claim_id": record.claim_id,
                "sender_id": record.sender_id,
                "content": record.content,
                "created_at": iso(record.created_at),
                "sender": user_summary(sender),
            }
        )
    return result


def message_view(record: ClaimMessage) -> dict:
    return message_views([record])[0]
