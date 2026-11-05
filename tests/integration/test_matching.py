"""GET /v1/matches: ownership, Top3 shape, score/reasons/rule_version."""

from __future__ import annotations

import pytest

from claimtest.api import (
    Api,
    Paths,
    assert_error,
    expect_status,
    field,
    json_object,
    unwrap_items,
)
from claimtest.privacy import assert_no_identity_fields


def _lost_item_id(scenario) -> object:
    value = scenario.claimant("alice").lost_item_id
    if value is None:
        pytest.skip("seed scenario is missing claimants.alice.lost_item_id")
    return value


def test_matches_return_top3_with_explanations(api: Api, scenario):
    lost_item_id = _lost_item_id(scenario)
    response = api.matches(lost_item_id, "alice")
    expect_status(response, 200)
    payload = json_object(response)
    items = unwrap_items(payload)
    assert len(items) <= 3

    rule_version = payload.get("rule_version")
    if not rule_version and isinstance(payload.get("data"), dict):
        rule_version = payload["data"].get("rule_version")
    if not rule_version and items:
        rule_version = field(items[0], "rule_version")
    assert isinstance(rule_version, str) and rule_version, (
        "matching response must expose rule_version"
    )

    for item in items:
        assert isinstance(item, dict)
        score = field(item, "score")
        assert isinstance(score, (int, float)), f"missing numeric score: {item}"
        reasons = field(item, "reasons", "reason")
        if isinstance(reasons, str):
            reasons = [reasons]
        assert isinstance(reasons, list) and reasons, f"reasons must be non-empty: {item}"
        assert item.get("item", {}).get("id")
        assert_no_identity_fields(item, context="matching recommendation")

    threshold = payload.get("threshold")
    if isinstance(threshold, (int, float)):
        assert all(field(item, "score") >= threshold for item in items)
    assert_no_identity_fields(payload, context="matching response")


def test_matches_are_owner_only(api: Api, scenario):
    lost_item_id = _lost_item_id(scenario)
    assert_error(api.matches(lost_item_id, "bob"), 403)
    assert_error(api.matches(lost_item_id, "outsider"), 403)


def test_matches_reject_non_lost_item_and_missing_item(api: Api, scenario):
    # A found listing is rejected as non-lost only for its owner; for another actor
    # the ownership check fires first (403), which is also covered here.
    assert_error(api.matches(scenario.found_id, "finder"), 422)
    assert_error(api.matches(scenario.found_id, "alice"), 403)
    assert_error(api.matches("T-NO-SUCH-LOST", "alice"), 404)


def test_matches_require_bearer(api: Api, scenario):
    lost_item_id = _lost_item_id(scenario)
    response = api.raw("GET", Paths.MATCHES, params={"item_id": lost_item_id})
    assert_error(response, 401)
