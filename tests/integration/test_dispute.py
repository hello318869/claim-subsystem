"""Dispute lifecycle and anonymized export."""

from __future__ import annotations

from typing import Any

import pytest

from claimtest.api import (
    Api,
    assert_error,
    claim_status,
    entity_id,
    expect_status,
    json_object,
    unwrap_entity,
)
from claimtest.privacy import assert_no_actor_identifiers, assert_no_identity_fields

REASON = "交接时发现物品细节与描述不一致，需要复核。"
ANON_ACTORS = ("alice", "bob", "outsider")


def _approved_claim(api: Api, scenario) -> object:
    claim_id = entity_id(unwrap_entity(api.create_claim(scenario, "alice")))
    expect_status(api.approve(claim_id, "finder"), 200)
    return claim_id


def _disputed_claim(api: Api, scenario) -> object:
    claim_id = _approved_claim(api, scenario)
    expect_status(api.dispute(claim_id, "alice", REASON), 200)
    assert claim_status(api, claim_id, "alice") == "DISPUTED"
    return claim_id


def _assert_export_anonymized(response, *, context: str) -> Any:
    expect_status(response, 200)
    content_type = response.headers.get("content-type", "").lower()
    looks_json = "json" in content_type or response.text.lstrip().startswith(("{", "["))
    if looks_json:
        payload = response.json()
        assert isinstance(payload, (dict, list)), type(payload)
        assert_no_identity_fields(payload, context=context)
        assert_no_actor_identifiers(payload, context=context, actors=ANON_ACTORS)
        return payload
    text = response.text
    forbidden = (
        "user_id",
        "owner_id",
        "publisher_id",
        "real_name",
        "phone",
        "email",
        "id_number",
    )
    lowered = text.lower()
    for token in forbidden:
        assert token not in lowered, f"{context} CSV/text contains {token!r}"
    assert_no_actor_identifiers(text, context=context, actors=ANON_ACTORS)
    return text


def test_either_party_can_dispute_approved_claim(api: Api, scenario):
    claim_id = _approved_claim(api, scenario)
    response = api.dispute(claim_id, "finder", REASON)
    expect_status(response, 200)
    assert claim_status(api, claim_id, "alice") == "DISPUTED"
    assert claim_status(api, claim_id, "finder") == "DISPUTED"


def test_dispute_requires_approved_state(api: Api, scenario):
    claim_id = entity_id(unwrap_entity(api.create_claim(scenario, "alice")))
    assert_error(api.dispute(claim_id, "alice", REASON), 409)
    expect_status(api.reject(claim_id, "finder", "信息不符"), 200)
    assert_error(api.dispute(claim_id, "alice", REASON), 409)


def test_dispute_requires_reason_and_party(api: Api, scenario):
    claim_id = _approved_claim(api, scenario)
    assert_error(api.dispute(claim_id, "alice", ""), 422)
    assert_error(api.dispute(claim_id, "outsider", REASON), 403)


def test_disputed_claim_blocks_state_changes(api: Api, scenario):
    claim_id = _disputed_claim(api, scenario)

    assert_error(api.approve(claim_id, "finder"), 409)
    assert_error(api.withdraw(claim_id, "alice"), 409)
    assert_error(api.reject(claim_id, "finder", "补充理由"), 409)
    expect_status(api.messages(claim_id, "alice", after=0), 200)


def test_disputed_claim_messages_are_read_only(api: Api, scenario):
    # Frozen policy: DISPUTED is a terminal, read-only state.  The current backend
    # includes DISPUTED in CHAT_OPEN_STATES; this assertion deliberately fails and is
    # reported as a backend defect rather than changed to match the implementation.
    claim_id = _disputed_claim(api, scenario)
    response = api.post(
        f"/v1/claims/{claim_id}/messages", actor="alice", json={"text": "复核一下"}
    )
    assert_error(response, 409)


def test_dispute_export_is_anonymized(api: Api, scenario):
    claim_id = _disputed_claim(api, scenario)
    alice_export = api.dispute_export(claim_id, "alice")
    payload = _assert_export_anonymized(alice_export, context="dispute export (alice)")
    assert payload is not None

    finder_export = api.dispute_export(claim_id, "finder")
    _assert_export_anonymized(finder_export, context="dispute export (finder)")

    assert_error(api.dispute_export(claim_id, "outsider"), 403)
