"""On-demand explainable matching (C, contract §6.3).

Rules are computed per request and never stored.  Scores are rule points from 0 to 100, not a
probability of finding the owner; private evidence and messages never take part.
"""

from __future__ import annotations

from datetime import timedelta
from unicodedata import category as unicode_category

from claims.services.claims import PUBLIC_POST_STATUSES
from common.contracts import Post as PostRecord
from common.contracts import UserSummary, post_summary
from common.errors import AppError
from posts import services as post_service

MIN_LIMIT = 1
MAX_LIMIT = 20
MAX_AGE = timedelta(days=30)
NEAR = timedelta(hours=72)


def _title_bigrams(title: str) -> set[tuple[str, str]]:
    characters = [
        char
        for char in title.lower()
        if not char.isspace() and not unicode_category(char).startswith("P")
    ]
    return set(zip(characters, characters[1:], strict=False))


def _score(source: PostRecord, candidate: PostRecord) -> tuple[int, list[str]]:
    source_is_lost = source.post_type == "lost"
    source_time = source.occurred_at
    elapsed = (
        candidate.occurred_at - source_time
        if source_is_lost
        else source_time - candidate.occurred_at
    )
    if not timedelta(0) <= elapsed <= MAX_AGE:
        return -1, []

    score = 40
    reasons = ["category_same"]
    if candidate.location.id == source.location.id:
        score += 30
        reasons.append("location_same")
    if elapsed <= NEAR:
        score += 20
        reasons.append("time_near")
    source_bigrams = _title_bigrams(source.title)
    if source_bigrams and not source_bigrams.isdisjoint(_title_bigrams(candidate.title)):
        score += 10
        reasons.append("keyword_overlap")
    return score, reasons


def find_matches(actor: UserSummary, post_id: str, limit: int) -> dict:
    if not MIN_LIMIT <= limit <= MAX_LIMIT:
        raise AppError(400, "VALIDATION_ERROR", "limit 必须在 1 至 20 之间", field="limit")

    source = post_service.get_post_for_claim(post_id)
    if source is None:
        raise AppError(404, "NOT_FOUND", "信息不存在")
    if source.publisher.id != actor.id:
        if source.status not in PUBLIC_POST_STATUSES:
            raise AppError(404, "NOT_FOUND", "信息不存在")
        raise AppError(403, "FORBIDDEN", "只能查看本人发布信息的匹配结果")
    if source.status != "open" or source.post_type not in ("lost", "found"):
        raise AppError(409, "STATE_CONFLICT", "该信息当前不可匹配")

    target_type = "found" if source.post_type == "lost" else "lost"
    ranked: list[tuple[PostRecord, int, list[str]]] = []
    for candidate in post_service.list_match_candidates(source):
        if (
            candidate.post_type != target_type
            or candidate.campus.id != source.campus.id
            or candidate.category.id != source.category.id
            or candidate.status != "open"
            or candidate.publisher.id == actor.id
        ):
            continue
        score, reasons = _score(source, candidate)
        if score < 0:
            continue
        ranked.append((candidate, score, reasons))

    ranked.sort(
        key=lambda match: (match[1], match[0].created_at, match[0].id),
        reverse=True,
    )
    return {
        "source_post_id": source.id,
        "items": [
            {"post": post_summary(candidate), "score": score, "reasons": reasons}
            for candidate, score, reasons in ranked[:limit]
        ],
    }
