from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.errors import AppError
from app.team.contracts import Label, Post, UserSummary, post_summary
from app.team.matching import find_matches


BASE_TIME = datetime(2026, 10, 7, 1, 30, tzinfo=timezone.utc)
OWNER = UserSummary(id="owner", nickname="失物发布者", is_campus_verified=True, verification_mode="demo")
OTHER = UserSummary(id="other", nickname="其他发布者", is_campus_verified=True, verification_mode="demo")


def _post(post_id: str, post_type: str, **overrides) -> Post:
    fields = {
        "id": post_id,
        "post_type": post_type,
        "title": "A B，钥-匙",
        "category": Label(id="keys", name="钥匙"),
        "campus": Label(id="main", name="主校区"),
        "location": Label(id="library", name="图书馆"),
        "occurred_at": BASE_TIME,
        "status": "open",
        "cover_image": None,
        "publisher": OTHER,
        "created_at": BASE_TIME,
        "updated_at": BASE_TIME,
    }
    return Post(**(fields | overrides))


class _Posts:
    def __init__(self, source: Post | None, candidates: tuple[Post, ...] = ()) -> None:
        self.source = source
        self.candidates = candidates
        self.listed = False

    def get_post_for_claim(self, session: Session, post_id: str, *, lock: bool = False) -> Post | None:
        assert not lock
        if self.source is not None and self.source.id == post_id:
            return self.source
        return None

    def list_match_candidates(self, session: Session, source_post: Post) -> tuple[Post, ...]:
        assert source_post is self.source
        self.listed = True
        return self.candidates


@pytest.mark.parametrize("source_type", ["lost", "found"])
def test_both_directions_score_the_same_pair_at_72_hours(source_type: str):
    # The database can supply naive UTC while B's adapter can supply an aware value.
    lost_time = BASE_TIME.replace(tzinfo=None)
    found_time = (BASE_TIME + timedelta(hours=72)).astimezone(timezone(timedelta(hours=8)))
    times = {"lost": lost_time, "found": found_time}
    target_type = "found" if source_type == "lost" else "lost"
    source = _post("source", source_type, occurred_at=times[source_type], publisher=OWNER)
    candidate = _post("candidate", target_type, occurred_at=times[target_type], title="ab拾获")
    earlier_found_or_later_lost = found_time if source_type == "found" else lost_time
    invalid = _post(
        "invalid", target_type,
        occurred_at=earlier_found_or_later_lost + timedelta(seconds=1 if source_type == "found" else -1),
    )

    with Session() as session:
        result = find_matches(session, _Posts(source, (invalid, candidate)), OWNER, source.id, 10)

    assert result == {
        "source_post_id": "source",
        "items": [{
            "post": post_summary(candidate),
            "score": 100,
            "reasons": ["category_same", "location_same", "time_near", "keyword_overlap"],
        }],
    }


def test_hard_gates_and_the_inclusive_thirty_day_boundary():
    source = _post("source", "lost", publisher=OWNER)
    last_day = BASE_TIME + timedelta(days=30)
    boundary = _post(
        "boundary", "found", occurred_at=last_day,
        location=Label(id="annex", name="图书馆"), title=" A！",
    )
    candidates = (
        _post("same_type", "lost"),
        _post("other_campus", "found", campus=Label(id="east", name="主校区")),
        _post("other_category", "found", category=Label(id="cards", name="钥匙")),
        _post("reserved", "found", status="in_handover"),
        _post("completed", "found", status="completed"),
        _post("withdrawn", "found", status="withdrawn"),
        _post("same_owner", "found", publisher=OWNER),
        _post("too_late", "found", occurred_at=last_day + timedelta(microseconds=1)),
    )

    with Session() as session:
        empty = find_matches(session, _Posts(source, candidates), OWNER, source.id, 10)
        result = find_matches(session, _Posts(source, (*candidates, boundary)), OWNER, source.id, 10)

    assert empty == {"source_post_id": "source", "items": []}
    assert result["items"] == [{"post": post_summary(boundary), "score": 40, "reasons": ["category_same"]}]


def test_sort_scores_then_normalized_creation_times_then_ids_before_limit():
    source = _post("source", "lost", publisher=OWNER)
    next_day = BASE_TIME + timedelta(days=1)
    candidates = (
        _post("b", "found", created_at=next_day.replace(tzinfo=None)),
        _post("z", "found"),
        _post("w", "found", title="单", created_at=next_day + timedelta(days=1)),
        _post("c", "found", created_at=next_day.astimezone(timezone(timedelta(hours=8)))),
    )

    with Session() as session:
        result = find_matches(session, _Posts(source, candidates), OWNER, source.id, 3)

    assert [item["post"]["id"] for item in result["items"]] == ["c", "b", "z"]


@pytest.mark.parametrize(("status", "owner", "expected"), [
    (None, True, (404, "NOT_FOUND")),
    ("withdrawn", False, (404, "NOT_FOUND")),
    ("completed", False, (403, "FORBIDDEN")),
    ("in_handover", True, (409, "STATE_CONFLICT")),
    ("withdrawn", True, (409, "STATE_CONFLICT")),
])
def test_denied_sources_do_not_load_candidates(status, owner, expected):
    source = _post("source", "lost", status=status, publisher=OWNER) if status else None
    posts = _Posts(source)

    with Session() as session, pytest.raises(AppError) as exc_info:
        find_matches(session, posts, OWNER if owner else OTHER, "source", 10)

    assert (exc_info.value.status_code, exc_info.value.code) == expected
    assert not posts.listed


@pytest.mark.parametrize("limit", [0, 21])
def test_limit_outside_contract_range(limit):
    with Session() as session, pytest.raises(AppError) as exc_info:
        find_matches(session, _Posts(None), OWNER, "source", limit)

    assert (exc_info.value.status_code, exc_info.value.code, exc_info.value.field) == (
        400, "VALIDATION_ERROR", "limit",
    )
