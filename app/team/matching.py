"""On-demand matching for the shared campus Post contract."""

from __future__ import annotations

from datetime import timedelta
from unicodedata import category

from sqlalchemy.orm import Session

from app.clock import to_db
from app.errors import AppError
from app.team.contracts import Post, PostService, UserSummary, post_summary


def _title_bigrams(title: str) -> set[tuple[str, str]]:
    characters = [
        char for char in title.lower() if not char.isspace() and not category(char).startswith("P")
    ]
    return set(zip(characters, characters[1:]))


def find_matches(
    session: Session,
    posts: PostService,
    actor: UserSummary,
    post_id: str,
    limit: int,
) -> dict:
    if not 1 <= limit <= 20:
        raise AppError(400, "VALIDATION_ERROR", "limit 必须在 1 至 20 之间", field="limit")

    source = posts.get_post_for_claim(session, post_id)
    if source is None:
        raise AppError(404, "NOT_FOUND", "信息不存在")
    if source.publisher.id != actor.id:
        if source.status not in ("open", "in_handover", "completed"):
            raise AppError(404, "NOT_FOUND", "信息不存在")
        raise AppError(403, "FORBIDDEN", "只能查看本人发布信息的匹配结果")
    if source.status != "open" or source.post_type not in ("lost", "found"):
        raise AppError(409, "STATE_CONFLICT", "该信息当前不可匹配")

    source_is_lost = source.post_type == "lost"
    target_type = "found" if source_is_lost else "lost"
    source_time = to_db(source.occurred_at)
    source_bigrams = _title_bigrams(source.title)
    ranked: list[tuple[Post, int, list[str]]] = []
    for candidate in posts.list_match_candidates(session, source):
        if (
            candidate.post_type != target_type
            or candidate.campus.id != source.campus.id
            or candidate.category.id != source.category.id
            or candidate.status != "open"
            or candidate.publisher.id == actor.id
        ):
            continue

        candidate_time = to_db(candidate.occurred_at)
        elapsed = candidate_time - source_time if source_is_lost else source_time - candidate_time
        if not timedelta(0) <= elapsed <= timedelta(days=30):
            continue

        score = 40
        reasons = ["category_same"]
        if candidate.location.id == source.location.id:
            score += 30
            reasons.append("location_same")
        if elapsed <= timedelta(hours=72):
            score += 20
            reasons.append("time_near")
        if source_bigrams and not source_bigrams.isdisjoint(_title_bigrams(candidate.title)):
            score += 10
            reasons.append("keyword_overlap")
        ranked.append((candidate, score, reasons))

    ranked.sort(key=lambda match: (match[1], to_db(match[0].created_at), match[0].id), reverse=True)
    return {
        "source_post_id": source.id,
        "items": [
            {"post": post_summary(candidate), "score": score, "reasons": reasons}
            for candidate, score, reasons in ranked[:limit]
        ],
    }
