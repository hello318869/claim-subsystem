"""Explainable matching rules and permissions (§6.3)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from posts.models import Campus, Location

pytestmark = pytest.mark.django_db


def assert_error(response, status: int, code: str) -> dict:
    assert response.status_code == status, response.content
    body = response.json()
    assert body["code"] == code, body
    return body


@pytest.fixture
def base_time():
    return timezone.now() - timedelta(hours=10)


def lost_post(make_post, base_time, **overrides):
    values = {
        "post_type": "lost",
        "title": "蓝色水杯",
        "publisher_id": "alice",
        "occurred_at": base_time,
        "location_id": "library",
    }
    values.update(overrides)
    return make_post(**values)


def found_post(make_post, base_time, *, title="校卡套", hours_after=2, **overrides):
    values = {
        "post_type": "found",
        "title": title,
        "publisher_id": "finder",
        "occurred_at": base_time + timedelta(hours=hours_after),
        "location_id": "library",
    }
    values.update(overrides)
    return make_post(**values)


def matches(actors, post_id, actor="alice", **params):
    return actors[actor].get(f"/posts/{post_id}/matches", params or None)


def test_full_score_lists_every_reason_in_contract_order(actors, make_post, base_time):
    source = lost_post(make_post, base_time)
    candidate = found_post(make_post, base_time, title="蓝色水杯带贴纸")

    data = matches(actors, source.id).json()["data"]
    assert data["source_post_id"] == source.id
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["score"] == 100
    assert item["reasons"] == [
        "category_same",
        "location_same",
        "time_near",
        "keyword_overlap",
    ]
    assert item["post"]["id"] == candidate.id
    assert set(item["post"]) == {
        "id",
        "post_type",
        "title",
        "category",
        "campus",
        "location",
        "occurred_at",
        "status",
        "cover_image",
        "publisher",
        "created_at",
        "updated_at",
    }
    assert item["post"]["publisher"]["id"] == "finder"
    assert item["post"]["cover_image"] is None


def test_category_and_location_score_without_keyword_overlap(actors, make_post, base_time):
    source = lost_post(make_post, base_time)
    found_post(make_post, base_time, title="校卡套")

    item = matches(actors, source.id).json()["data"]["items"][0]
    assert item["score"] == 90
    assert item["reasons"] == ["category_same", "location_same", "time_near"]


def test_different_location_loses_thirty_points(actors, make_post, base_time):
    source = lost_post(make_post, base_time)
    found_post(make_post, base_time, location_id="gym")

    item = matches(actors, source.id).json()["data"]["items"][0]
    assert item["score"] == 60
    assert item["reasons"] == ["category_same", "time_near"]


def test_elapsed_between_72_hours_and_30_days_loses_time_points(actors, make_post, base_time):
    source = lost_post(make_post, base_time)
    found_post(make_post, base_time, hours_after=24 * 10)

    item = matches(actors, source.id).json()["data"]["items"][0]
    assert item["score"] == 70
    assert item["reasons"] == ["category_same", "location_same"]


def test_candidates_older_than_30_days_are_excluded(actors, make_post, base_time):
    source = lost_post(make_post, base_time)
    found_post(make_post, base_time, hours_after=24 * 31)
    assert matches(actors, source.id).json()["data"]["items"] == []


def test_found_before_lost_is_excluded(actors, make_post, base_time):
    source = lost_post(make_post, base_time)
    found_post(make_post, base_time, hours_after=-2)
    assert matches(actors, source.id).json()["data"]["items"] == []


def test_candidates_must_be_open_opposite_type_same_campus_and_category(
    actors, make_post, base_time
):
    source = lost_post(make_post, base_time)

    # Every post below violates one hard condition.
    found_post(make_post, base_time, status="withdrawn")
    found_post(make_post, base_time, status="in_handover")
    found_post(make_post, base_time, status="completed")
    lost_post(make_post, base_time, title="另一条失物", publisher_id="bob")
    found_post(make_post, base_time, category_id="keys")
    found_post(make_post, base_time, publisher_id="alice")

    Campus.objects.create(id="east", name="东校区")
    Location.objects.create(id="east_lib", campus_id="east", name="东区图书馆", sort_order=1)
    found_post(make_post, base_time, location_id="east_lib")

    assert matches(actors, source.id).json()["data"]["items"] == []


def test_found_source_matches_lost_candidates(actors, make_post, base_time):
    source = found_post(make_post, base_time, publisher_id="alice", title="蓝色水杯")
    candidate = lost_post(
        make_post,
        base_time,
        title="蓝色水杯",
        publisher_id="finder",
        occurred_at=base_time - timedelta(hours=1),
    )

    items = matches(actors, source.id).json()["data"]["items"]
    assert [item["post"]["id"] for item in items] == [candidate.id]


def test_results_are_ordered_by_score_then_recency(actors, make_post, base_time):
    source = lost_post(make_post, base_time)
    best = found_post(make_post, base_time, title="蓝色水杯带贴纸")
    second = found_post(make_post, base_time, title="校卡套")
    third = found_post(make_post, base_time, title="校卡套", hours_after=24 * 10)

    items = matches(actors, source.id).json()["data"]["items"]
    assert [item["post"]["id"] for item in items] == [best.id, second.id, third.id]
    assert [item["score"] for item in items] == [100, 90, 70]


def test_limit_is_applied_and_validated(actors, make_post, base_time):
    source = lost_post(make_post, base_time)
    found_post(make_post, base_time)
    found_post(make_post, base_time, title="蓝色水杯")

    assert len(matches(actors, source.id, limit=1).json()["data"]["items"]) == 1
    for value in ("0", "21", "abc"):
        assert_error(matches(actors, source.id, limit=value), 400, "VALIDATION_ERROR")


def test_only_the_owner_can_read_matches(actors, make_post, base_time):
    source = lost_post(make_post, base_time)
    assert_error(matches(actors, source.id, actor="bob"), 403, "FORBIDDEN")
    assert_error(matches(actors, source.id, actor="outsider"), 403, "FORBIDDEN")


def test_withdrawn_source_is_hidden_from_others(actors, make_post, base_time):
    source = lost_post(make_post, base_time, status="withdrawn")
    assert_error(matches(actors, source.id, actor="bob"), 404, "NOT_FOUND")


@pytest.mark.parametrize("status", ("withdrawn", "in_handover", "completed"))
def test_owner_needs_an_open_post_to_match(actors, make_post, base_time, status):
    source = lost_post(make_post, base_time, status=status)
    assert_error(matches(actors, source.id), 409, "STATE_CONFLICT")


def test_unknown_source_is_not_found(actors, reference_data):
    assert_error(matches(actors, "NO-SUCH-POST"), 404, "NOT_FOUND")


def test_short_source_title_disables_the_keyword_bonus(actors, make_post, base_time):
    source = lost_post(make_post, base_time, title="杯")
    found_post(make_post, base_time, title="杯")
    item = matches(actors, source.id).json()["data"]["items"][0]
    assert item["score"] == 90
    assert "keyword_overlap" not in item["reasons"]


def test_private_claim_data_is_not_part_of_matching(actors, make_post, base_time):
    from claims.services.matching import find_matches
    from tests.support import PROOF, apply_claim

    source = lost_post(make_post, base_time)
    candidate = found_post(make_post, base_time, publisher_id="bob")
    apply_claim(actors, source.id, "bob", PROOF)  # bob claims alice's lost post

    from common.contracts import UserSummary

    actor = UserSummary("alice", "小林", True, "demo")
    result = find_matches(actor, source.id, 10)
    assert [item["post"]["id"] for item in result["items"]] == [candidate.id]
    assert PROOF not in str(result)
