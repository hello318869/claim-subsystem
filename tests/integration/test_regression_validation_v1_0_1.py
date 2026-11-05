"""V1.0.1 regression: blank-input validation and deadline-expiry persistence."""

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

BLANKS = ("   ", "\n\t")


def _claim(api: Api, scenario, actor: str = "alice") -> str:
    return str(entity_id(unwrap_entity(api.create_claim(scenario, actor))))


def _approved(api: Api, scenario) -> str:
    claim_id = _claim(api, scenario)
    expect_status(api.approve(claim_id, "finder"), 200)
    assert claim_status(api, claim_id, "alice") == "APPROVED"
    return claim_id


@pytest.mark.parametrize("blank", BLANKS)
def test_blank_evidence_is_422_and_not_stored(api: Api, scenario, db_tools, blank):
    body = scenario.claimant("alice").create_payload(blank)
    response = api.post(Paths.CLAIMS, actor="alice", json=body)
    assert_error(response, 422)
    assert db_tools.count_claims_for_item(scenario.found_id) == 0


@pytest.mark.parametrize("blank", BLANKS)
def test_blank_message_is_422_and_not_stored(api: Api, scenario, db_tools, blank):
    claim_id = _claim(api, scenario)
    response = api.post(Paths.messages(claim_id), actor="alice", json={"text": blank})
    assert_error(response, 422)
    assert db_tools.count_messages(claim_id) == 0


@pytest.mark.parametrize("blank", BLANKS)
def test_blank_reject_reason_is_422_and_does_not_mutate(api: Api, scenario, db_tools, blank):
    claim_id = _claim(api, scenario)
    response = api.reject(claim_id, "finder", blank)
    assert_error(response, 422)
    assert db_tools.get_claim_status(claim_id) == "PENDING"
    assert db_tools.get_claim_reason(claim_id) is None


@pytest.mark.parametrize("blank", BLANKS)
def test_blank_dispute_reason_is_422_and_does_not_mutate(api: Api, scenario, db_tools, blank):
    claim_id = _approved(api, scenario)
    response = api.dispute(claim_id, "alice", blank)
    assert_error(response, 422)
    assert db_tools.get_claim_status(claim_id) == "APPROVED"
    assert db_tools.get_claim_reason(claim_id) is None


# ResetRequest.reason is optional (default "" in the frozen V1.0.1 schema);
# only reject/dispute ReasonRequest is strict-non-blank.  The old v1.0 test for
# a valid reset reason remains in test_handover_flow.py.


def test_reset_after_absolute_deadline_is_410_and_expired_is_persisted(
    api: Api, scenario, db_tools
):
    claim_id = _approved(api, scenario)
    db_tools.expire_handover_deadline(claim_id)

    response = api.reset_handover(claim_id, "alice", "超过 24 小时后的重置")
    error = assert_error(response, 410)
    assert error["code"] == "code_expired"

    # The failed write must still persist the terminal EXPIRED state, not roll it back.
    assert db_tools.get_claim_status(claim_id) == "EXPIRED"
    assert claim_status(api, claim_id, "alice") == "EXPIRED"
