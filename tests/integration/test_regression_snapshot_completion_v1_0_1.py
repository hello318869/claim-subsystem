"""V1.0.1 regression: snapshot status gate and completed-claim history."""

from __future__ import annotations

from claimtest.api import (
    Api,
    Paths,
    assert_error,
    claim_status,
    entity_id,
    expect_status,
    unwrap_entity,
)


def _claim(api: Api, scenario, actor: str = "alice") -> str:
    return str(entity_id(unwrap_entity(api.create_claim(scenario, actor))))


def test_non_published_snapshot_cannot_be_claimed(api: Api, scenario, db_tools):
    body = scenario.claimant("alice").create_payload(
        "外部快照状态回归：该记录当前不是 published。"
    )

    for status in ("withdrawn", "claimed"):
        db_tools.set_listing_status(scenario.found_id, status)
        response = api.post(Paths.CLAIMS, actor="alice", json=body)
        error = assert_error(response, 422)
        assert error["code"] == "not_claimable"
        assert db_tools.count_claims_for_item(scenario.found_id) == 0

    db_tools.set_listing_status(scenario.found_id, "published")
    response = api.post(Paths.CLAIMS, actor="alice", json=body)
    expect_status(response, 201)
    assert db_tools.count_claims_for_item(scenario.found_id) == 1


def test_completed_claim_dual_confirmation_history_is_consistent(api: Api, scenario):
    claim_id = _claim(api, scenario)
    expect_status(api.approve(claim_id, "finder"), 200)
    approved = unwrap_entity(api.get_claim(claim_id, "alice"))
    deadline_before = approved["handover_deadline"]

    alice_code = unwrap_entity(api.get_code(claim_id, "alice"))["code"]
    finder_code = unwrap_entity(api.get_code(claim_id, "finder"))["code"]
    expect_status(api.confirm_handover(claim_id, "alice", finder_code), 200)
    expect_status(api.confirm_handover(claim_id, "finder", alice_code), 200)

    alice_view = unwrap_entity(api.get_claim(claim_id, "alice"))
    finder_view = unwrap_entity(api.get_claim(claim_id, "finder"))
    for view, role in ((alice_view, "applicant"), (finder_view, "finder")):
        assert view["status"] == "COMPLETED"
        assert view["my_role"] == role
        assert view["confirmed_by_me"] is True
        assert view["confirmed_by_counterpart"] is True
        assert view["handover_deadline"] == deadline_before
        assert view["reason"] is None

    listing = unwrap_entity(api.get(Paths.listing(scenario.found_id), actor="alice"))
    assert listing["status"] == "claimed"
    assert listing["claimable"] is False

    assert_error(api.get_code(claim_id, "alice"), 409)


def test_dispute_clears_confirmation_flags(api: Api, scenario):
    claim_id = _claim(api, scenario)
    expect_status(api.approve(claim_id, "finder"), 200)
    finder_code = unwrap_entity(api.get_code(claim_id, "finder"))["code"]
    expect_status(api.confirm_handover(claim_id, "alice", finder_code), 200)
    before = unwrap_entity(api.get_claim(claim_id, "alice"))
    assert before["confirmed_by_me"] is True

    expect_status(api.dispute(claim_id, "alice", "交接地点无法达成一致"), 200)
    after = unwrap_entity(api.get_claim(claim_id, "alice"))
    assert after["status"] == "DISPUTED"
    assert after["confirmed_by_me"] is False
    assert after["confirmed_by_counterpart"] is False
