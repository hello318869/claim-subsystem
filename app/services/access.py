"""Shared membership helpers for claim-scoped resources."""

from __future__ import annotations

from app.errors import AppError
from app.models import Claim


def membership(claim: Claim, actor: str) -> str:
    if claim.applicant_id == actor:
        return "applicant"
    if claim.finder_id == actor:
        return "finder"
    raise AppError(403, "forbidden", "无权访问该认领申请")


def counterpart(role: str) -> str:
    return "finder" if role == "applicant" else "applicant"
