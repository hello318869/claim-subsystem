"""State machine: PENDING -> APPROVED/REJECTED/WITHDRAWN/CLOSED_OTHER; terminal read-only."""

from __future__ import annotations

import pytest

from claimtest.api import (
    Api,
    Paths,
    assert_error,
    claim_status,
    entity_id,
    expect_status,
    unwrap_entity,
)
from claimtest.privacy import assert_no_identity_fields

REASON = "外观特征与登记信息不符，请补充物品编号。"


def _create(api: Api, scenario, actor: str) -> object:
    return entity_id(unwrap_entity(api.create_claim(scenario, actor)))


def _two_claims(api: Api, scenario) -> tuple[object, object]:
    return _create(api, scenario, "alice"), _create(api, scenario, "bob")


def test_approve_sets_approved_and_closes_other_submitted_claims(api: Api, scenario):
    alice_claim, bob_claim = _two_claims(api, scenario)
    assert claim_status(api, alice_claim, "alice") == "PENDING"
    assert claim_status(api, bob_claim, "bob") == "PENDING"

    response = api.approve(alice_claim, "finder")
    expect_status(response, 200)
    assert claim_status(api, alice_claim, "alice") == "APPROVED"
    assert claim_status(api, bob_claim, "bob") == "CLOSED_OTHER"

    late = api.approve(bob_claim, "finder")
    assert_error(late, 409)


def test_only_found_owner_can_approve(api: Api, scenario):
    claim_id = _create(api, scenario, "alice")
    for actor in ("alice", "bob", "outsider"):
        response = api.approve(claim_id, actor)
        assert_error(response, 403)
    assert claim_status(api, claim_id, "alice") == "PENDING"
    expect_status(api.approve(claim_id, "finder"), 200)
    assert claim_status(api, claim_id, "alice") == "APPROVED"


def test_reject_requires_owner_and_reason(api: Api, scenario):
    claim_id = _create(api, scenario, "alice")

    assert_error(api.reject(claim_id, "alice", REASON), 403)
    assert_error(api.reject(claim_id, "outsider", REASON), 403)
    assert_error(api.reject(claim_id, "finder", None), 422)
    assert_error(api.reject(claim_id, "finder", ""), 422)
    assert claim_status(api, claim_id, "alice") == "PENDING"

    expect_status(api.reject(claim_id, "finder", REASON), 200)
    assert claim_status(api, claim_id, "alice") == "REJECTED"


def test_withdraw_is_claimant_only(api: Api, scenario):
    claim_id = _create(api, scenario, "alice")

    assert_error(api.withdraw(claim_id, "bob"), 403)
    assert_error(api.withdraw(claim_id, "finder"), 403)
    assert_error(api.withdraw(claim_id, "outsider"), 403)
    assert claim_status(api, claim_id, "alice") == "PENDING"

    expect_status(api.withdraw(claim_id, "alice"), 200)
    assert claim_status(api, claim_id, "alice") == "WITHDRAWN"
    assert_error(api.withdraw(claim_id, "alice"), 409)


def test_withdraw_is_not_allowed_after_approval(api: Api, scenario):
    claim_id = _create(api, scenario, "alice")
    expect_status(api.approve(claim_id, "finder"), 200)
    assert claim_status(api, claim_id, "alice") == "APPROVED"
    assert_error(api.withdraw(claim_id, "alice"), 409)


def test_approve_rejected_claim_is_409(api: Api, scenario):
    claim_id = _create(api, scenario, "alice")
    expect_status(api.reject(claim_id, "finder", REASON), 200)
    assert_error(api.approve(claim_id, "finder"), 409)
    assert_error(api.withdraw(claim_id, "alice"), 409)


def test_approve_withdrawn_claim_is_409(api: Api, scenario):
    claim_id = _create(api, scenario, "alice")
    expect_status(api.withdraw(claim_id, "alice"), 200)
    assert_error(api.approve(claim_id, "finder"), 409)
    assert_error(api.reject(claim_id, "finder", REASON), 409)


def test_reject_approved_claim_is_409(api: Api, scenario):
    claim_id = _create(api, scenario, "alice")
    expect_status(api.approve(claim_id, "finder"), 200)
    assert_error(api.reject(claim_id, "finder", REASON), 409)
    assert claim_status(api, claim_id, "alice") == "APPROVED"


def test_rejecting_one_claim_does_not_close_the_other(api: Api, scenario):
    alice_claim, bob_claim = _two_claims(api, scenario)
    expect_status(api.reject(alice_claim, "finder", REASON), 200)
    assert claim_status(api, alice_claim, "alice") == "REJECTED"
    assert claim_status(api, bob_claim, "bob") == "PENDING"
    expect_status(api.approve(bob_claim, "finder"), 200)
    assert claim_status(api, bob_claim, "bob") == "APPROVED"


def test_terminal_claim_is_read_only(api: Api, scenario):
    claim_id = _create(api, scenario, "alice")
    expect_status(api.withdraw(claim_id, "alice"), 200)
    assert claim_status(api, claim_id, "alice") == "WITHDRAWN"

    detail = api.get_claim(claim_id, "alice")
    expect_status(detail, 200)
    assert_no_identity_fields(unwrap_entity(detail), context="terminal claim detail")

    assert_error(api.approve(claim_id, "finder"), 409)
    assert_error(api.reject(claim_id, "finder", REASON), 409)
    assert_error(api.post(Paths.messages(claim_id), actor="alice", json={"text": "还在吗"}), 409)
    expect_status(api.messages(claim_id, "alice", after=0), 200)


def test_unknown_claim_transition_is_404(api: Api):
    assert_error(api.approve(987654321, "finder"), 404)
    assert_error(api.withdraw(987654321, "alice"), 404)
    assert_error(api.reject(987654321, "finder", REASON), 404)
