"""Explainable rule-based recommendation. Never approves anything and never pushes."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app import serializers
from app.config import Settings
from app.errors import AppError
from app.repos import listing_repo
from app.rules import rank_candidates


def match_for_lost_item(session: Session, settings: Settings, actor: str, item_id: str) -> dict:
    item = listing_repo.get(session, item_id)
    if item is None:
        raise AppError(404, "not_found", "记录不存在")
    if item.publisher_user_id != actor:
        raise AppError(403, "forbidden", "只能查询自己发布的失物记录")
    if item.kind != "lost":
        raise AppError(422, "not_claimable", "只有失物记录可以查询匹配推荐")

    founds = listing_repo.lock_free_published_founds(session)
    candidates = rank_candidates(
        item,
        founds,
        threshold=settings.match_threshold,
        limit=settings.match_candidate_limit,
    )
    by_id = {row.item_id: row for row in founds}
    approved = listing_repo.approved_claim_ids(session, [c.item_id for c in candidates])
    return {
        "item_id": item.item_id,
        "rule_version": settings.match_rule_version,
        "threshold": settings.match_threshold,
        "candidates": [
            {
                "item": serializers.public_listing(by_id[candidate.item_id], approved=candidate.item_id in approved),
                "score": candidate.score,
                "reasons": list(candidate.reasons),
            }
            for candidate in candidates
            if candidate.item_id in by_id
        ],
    }
