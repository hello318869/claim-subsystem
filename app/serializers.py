"""DTO builders.

These functions are the only place where model rows become API payloads, which keeps
``publisher_id`` / ``sender_id`` out of every response by construction.
"""

from __future__ import annotations

from app.clock import iso
from app.models import Claim, HandoverCode, ListingSnapshot, Message

ROLE_LABEL = {"applicant": "申请人", "finder": "拾获方"}


def alias_for(claim_id: str, role: str) -> str:
    return f"{ROLE_LABEL.get(role, '参与方')}-{claim_id[:6].upper()}"


def public_listing(item: ListingSnapshot, *, approved: bool = False) -> dict:
    status = "claimed" if approved else item.status
    return {
        "id": item.item_id,
        "kind": item.kind,
        "title": item.title,
        "category": item.category,
        "occurred_at": iso(item.occurred_at),
        "location": item.location,
        "description": item.description,
        "status": status,
        "claimable": item.kind == "found" and not approved and item.status == "published",
    }


def my_role(claim: Claim, actor: str) -> str:
    return "applicant" if claim.applicant_id == actor else "finder"


def counterpart_role(claim: Claim, actor: str) -> str:
    return "finder" if claim.applicant_id == actor else "applicant"


def claim_dto(claim: Claim, actor: str, code: HandoverCode | None = None) -> dict:
    role = my_role(claim, actor)
    other = counterpart_role(claim, actor)
    # Confirmations are live while APPROVED and kept as history after COMPLETED. Every other
    # state clears them so a rejected/expired/disputed claim never implies a confirmation.
    show_confirmations = claim.status in {"APPROVED", "COMPLETED"}
    confirmed_me = bool(code and show_confirmations and getattr(code, f"confirmed_{role}"))
    confirmed_other = bool(code and show_confirmations and getattr(code, f"confirmed_{other}"))
    return {
        "id": claim.id,
        "item_id": claim.item_id,
        "status": claim.status,
        "my_role": role,
        "evidence_text": claim.evidence_text,
        "item_number": claim.item_number,
        "reason": claim.reason,
        "confirmed_by_me": confirmed_me,
        "confirmed_by_counterpart": confirmed_other,
        "created_at": iso(claim.created_at),
        "updated_at": iso(claim.updated_at),
        "handover_deadline": iso(claim.handover_deadline),
    }


def message_dto(message: Message, claim: Claim, actor: str) -> dict:
    role = my_role(claim, actor)
    return {
        "id": message.id,
        "text": message.body,
        "sender_alias": alias_for(claim.id, message.sender_role),
        "is_mine": message.sender_role == role,
        "created_at": iso(message.created_at),
    }


def page_dto(items: list, total: int, page: int, page_size: int) -> dict:
    return {"items": items, "total": total, "page": page, "page_size": page_size}
