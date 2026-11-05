"""Handover codes, two-party confirmation, nonce reset, cooldown and 24h deadline."""

from __future__ import annotations

from datetime import datetime

import pytest

from claimtest.api import (
    Api,
    assert_error,
    claim_status,
    entity_id,
    expect_status,
    field,
    unwrap_entity,
)
from claimtest.privacy import assert_no_identity_fields

REASON = "物品特征需要重新核对。"


def _approved_claim(api: Api, scenario) -> object:
    claim_id = entity_id(unwrap_entity(api.create_claim(scenario, "alice")))
    expect_status(api.approve(claim_id, "finder"), 200)
    assert claim_status(api, claim_id, "alice") == "APPROVED"
    return claim_id


def _code(api: Api, claim_id: object, actor: str) -> str:
    response = api.get_code(claim_id, actor)
    expect_status(response, 200)
    entity = unwrap_entity(response)
    code = field(entity, "code")
    expires_at = field(entity, "expires_at")
    assert code is not None and str(code), f"{actor} code is empty"
    assert len(str(code)) == 8 and str(code).isdigit()
    assert isinstance(expires_at, str) and expires_at, "code response needs expires_at"
    datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    assert_no_identity_fields(entity, context=f"handover code ({actor})")
    return str(code)


def _wrong_code(api: Api, claim_id: object, attempts: int = 5) -> list:
    responses = []
    for _ in range(attempts):
        responses.append(api.confirm_handover(claim_id, "alice", "00000000"))
    return responses


def test_code_is_unavailable_before_approval(api: Api, scenario):
    claim_id = entity_id(unwrap_entity(api.create_claim(scenario, "alice")))
    assert_error(api.get_code(claim_id, "alice"), 409)


def test_each_party_sees_only_own_code(api: Api, scenario):
    claim_id = _approved_claim(api, scenario)
    alice_code = _code(api, claim_id, "alice")
    finder_code = _code(api, claim_id, "finder")
    assert alice_code != finder_code
    assert_error(api.get_code(claim_id, "outsider"), 403)


def test_approved_claim_has_24h_deadline(api: Api, scenario):
    claim_id = _approved_claim(api, scenario)
    detail = unwrap_entity(api.get_claim(claim_id, "alice"))
    assert detail["handover_deadline"] is not None
    deadline = datetime.fromisoformat(detail["handover_deadline"].replace("Z", "+00:00"))
    created = datetime.fromisoformat(detail["updated_at"].replace("Z", "+00:00"))
    assert 23.9 * 3600 <= (deadline - created).total_seconds() <= 24.1 * 3600


def test_wrong_code_is_422_and_does_not_complete(api: Api, scenario):
    claim_id = _approved_claim(api, scenario)
    _code(api, claim_id, "alice")
    _code(api, claim_id, "finder")

    response = api.confirm_handover(claim_id, "alice", "00000000")
    error = assert_error(response, 422)
    assert error["code"] == "invalid_code"
    assert "剩余" in error["message"]
    assert claim_status(api, claim_id, "alice") == "APPROVED"


def test_two_party_confirmation_completes_claim(api: Api, scenario):
    claim_id = _approved_claim(api, scenario)
    alice_code = _code(api, claim_id, "alice")
    finder_code = _code(api, claim_id, "finder")

    first = api.confirm_handover(claim_id, "alice", finder_code)
    expect_status(first, (200, 201))
    first_dto = unwrap_entity(first)
    assert first_dto["confirmed_by_me"] is True
    assert first_dto["confirmed_by_counterpart"] is False
    assert claim_status(api, claim_id, "alice") != "COMPLETED"

    second = api.confirm_handover(claim_id, "finder", alice_code)
    expect_status(second, (200, 201))
    assert claim_status(api, claim_id, "finder") == "COMPLETED"

    # The backend treats a repeated confirm on COMPLETED as an idempotent 200; the
    # state stays terminal and no new state change is possible.
    late = api.confirm_handover(claim_id, "alice", finder_code)
    expect_status(late, 200)
    assert claim_status(api, claim_id, "alice") == "COMPLETED"
    api.send_message(claim_id, "alice", "完成后还能发吗？", expect=409)


def test_reset_while_code_valid_is_not_allowed(api: Api, scenario):
    claim_id = _approved_claim(api, scenario)
    _code(api, claim_id, "alice")
    reset = api.reset_handover(claim_id, "alice", REASON)
    error = assert_error(reset, 409)
    assert error["code"] == "reset_not_allowed"


def test_reset_after_expiry_rotates_nonce_and_invalidates_old_code(
    api: Api, scenario, db_tools
):
    claim_id = _approved_claim(api, scenario)
    old_alice_code = _code(api, claim_id, "alice")
    old_finder_code = _code(api, claim_id, "finder")
    old_nonce = db_tools.get_code_row(claim_id)["nonce"]

    db_tools.expire_code(claim_id)
    assert_error(api.get_code(claim_id, "alice"), 410)

    reset = api.reset_handover(claim_id, "alice", REASON)
    expect_status(reset, 200)
    reset_body = reset.json()
    assert reset_body["reset_count"] == 1
    assert reset_body["counterparty_must_refetch"] is True
    assert reset_body["reason"] == REASON
    new_nonce = db_tools.get_code_row(claim_id)["nonce"]
    assert new_nonce != old_nonce

    stale = api.confirm_handover(claim_id, "alice", old_finder_code)
    error = assert_error(stale, 422)
    assert error["code"] == "invalid_code"
    assert claim_status(api, claim_id, "alice") == "APPROVED"

    new_alice_code = _code(api, claim_id, "alice")
    new_finder_code = _code(api, claim_id, "finder")
    assert new_alice_code != old_alice_code
    assert new_finder_code != old_finder_code
    expect_status(api.confirm_handover(claim_id, "alice", new_finder_code), (200, 201))
    expect_status(api.confirm_handover(claim_id, "finder", new_alice_code), (200, 201))
    assert claim_status(api, claim_id, "alice") == "COMPLETED"


def test_cooldown_429_then_reset_after_cooldown(api: Api, scenario, db_tools):
    claim_id = _approved_claim(api, scenario)
    _code(api, claim_id, "alice")
    _code(api, claim_id, "finder")

    wrong = _wrong_code(api, claim_id, attempts=5)
    for index, response in enumerate(wrong):
        expect_status(response, 422)
        assert f"{4 - index}" in response.json()["message"]

    cooling = api.confirm_handover(claim_id, "alice", "00000000")
    error = assert_error(cooling, 429)
    assert error["code"] == "cooldown_active"
    assert isinstance(error.get("retry_after_seconds"), int)
    assert error["retry_after_seconds"] > 0

    blocked_reset = api.reset_handover(claim_id, "alice", REASON)
    blocked = assert_error(blocked_reset, 409)
    assert blocked["code"] == "reset_not_allowed"

    db_tools.end_cooldown(claim_id, "applicant")
    reset = api.reset_handover(claim_id, "alice", REASON)
    expect_status(reset, 200)
    assert reset.json()["reset_count"] == 1

    new_alice = _code(api, claim_id, "alice")
    new_finder = _code(api, claim_id, "finder")
    expect_status(api.confirm_handover(claim_id, "alice", new_finder), (200, 201))
    expect_status(api.confirm_handover(claim_id, "finder", new_alice), (200, 201))
    assert claim_status(api, claim_id, "alice") == "COMPLETED"


def test_reset_limit_is_two(api: Api, scenario, db_tools):
    claim_id = _approved_claim(api, scenario)
    for expected in (1, 2):
        db_tools.expire_code(claim_id)
        reset = api.reset_handover(claim_id, "alice", f"第{expected}次")
        expect_status(reset, 200)
        assert reset.json()["reset_count"] == expected
    db_tools.expire_code(claim_id)
    third = api.reset_handover(claim_id, "alice", "第三次")
    error = assert_error(third, 409)
    assert error["code"] == "reset_not_allowed"


def test_reset_party_and_valid_reason(api: Api, scenario, db_tools):
    claim_id = _approved_claim(api, scenario)
    db_tools.expire_code(claim_id)
    assert_error(api.reset_handover(claim_id, "outsider", REASON), 403)
    # The revised V1.0.1 contract requires a non-blank reason; blank is covered by
    # the strict regression test in test_regression_validation_v1_0_1.py.
    reset = api.reset_handover(claim_id, "alice", REASON)
    expect_status(reset, 200)
    assert reset.json()["reason"] == REASON


def test_reset_before_approval_is_409(api: Api, scenario):
    claim_id = entity_id(unwrap_entity(api.create_claim(scenario, "alice")))
    assert_error(api.reset_handover(claim_id, "alice", REASON), 409)


def test_confirm_by_outsider_is_403(api: Api, scenario):
    claim_id = _approved_claim(api, scenario)
    alice_code = _code(api, claim_id, "alice")
    _code(api, claim_id, "finder")
    assert_error(api.confirm_handover(claim_id, "outsider", alice_code), 403)
    assert claim_status(api, claim_id, "alice") != "COMPLETED"


def test_expired_code_is_410(api: Api, scenario, db_tools):
    claim_id = _approved_claim(api, scenario)
    _code(api, claim_id, "alice")
    finder_code = _code(api, claim_id, "finder")

    db_tools.expire_code(claim_id)
    assert_error(api.get_code(claim_id, "alice"), 410)
    response = api.confirm_handover(claim_id, "alice", finder_code)
    error = assert_error(response, 410)
    assert error["code"] == "code_expired"
    assert claim_status(api, claim_id, "alice") != "COMPLETED"


def test_handover_deadline_expires_claim(api: Api, scenario, db_tools):
    claim_id = _approved_claim(api, scenario)
    _code(api, claim_id, "alice")
    finder_code = _code(api, claim_id, "finder")

    db_tools.expire_handover_deadline(claim_id)
    response = api.confirm_handover(claim_id, "alice", finder_code)
    error = assert_error(response, 410)
    assert error["code"] == "code_expired"
    assert claim_status(api, claim_id, "alice") == "EXPIRED"
    assert_error(api.get_code(claim_id, "alice"), 409)
    assert_error(api.reset_handover(claim_id, "alice", REASON), 409)
