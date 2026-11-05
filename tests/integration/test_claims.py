"""Claim creation, visibility and participant-only listing."""

from __future__ import annotations

from typing import Any

import pytest

from claimtest.api import (
    Api,
    Paths,
    assert_error,
    entity_id,
    expect_status,
    json_object,
    role_of,
    status_of,
    unwrap_entity,
    unwrap_items,
)
from claimtest.privacy import assert_no_identity_fields

EVIDENCE = "耳机盒盖内侧有小星星贴纸，左耳外壳有一道浅划痕。"


def _claim_ids(api: Api, actor: str) -> set[str]:
    ids: set[str] = set()
    for page in range(1, 41):
        response = api.get(
            Paths.CLAIMS, actor=actor, params={"page": page, "page_size": 50}
        )
        expect_status(response, 200)
        items = unwrap_items(json_object(response))
        page_items = [item for item in items if isinstance(item, dict)]
        ids.update(str(entity_id(item)) for item in page_items)
        if len(page_items) < 50:
            break
    return ids


def test_create_claim_and_participant_visibility(api: Api, scenario):
    created = api.create_claim(scenario, "alice", evidence_text=EVIDENCE)
    claim_id = entity_id(unwrap_entity(created))

    alice_view = unwrap_entity(api.get_claim(claim_id, "alice"))
    assert status_of(alice_view) == "PENDING"
    assert alice_view.get("evidence_text") == EVIDENCE
    alice_role = role_of(alice_view)
    assert_no_identity_fields(alice_view, context="claim detail (claimant)")

    finder_response = api.get_claim(claim_id, "finder")
    expect_status(finder_response, 200)
    finder_view = unwrap_entity(finder_response)
    assert finder_view.get("evidence_text") == EVIDENCE
    assert role_of(finder_view) != alice_role, "the two parties must see their own roles"
    assert_no_identity_fields(finder_view, context="claim detail (finder)")


def test_outsider_cannot_read_claim(api: Api, scenario):
    created = api.create_claim(scenario, "alice")
    claim_id = entity_id(unwrap_entity(created))
    response = api.get_claim(claim_id, "outsider")
    assert_error(response, 403)


def test_claim_list_only_contains_related_claims(api: Api, scenario):
    created = api.create_claim(scenario, "bob")
    claim_id = str(entity_id(unwrap_entity(created)))

    assert claim_id in _claim_ids(api, "bob")
    assert claim_id not in _claim_ids(api, "alice")
    assert claim_id not in _claim_ids(api, "outsider")


@pytest.mark.parametrize("missing", ["item_id", "evidence_text"])
def test_create_claim_requires_required_fields(api: Api, scenario, missing: str):
    body = scenario.claimant("alice").create_payload(EVIDENCE)
    body.pop(missing)
    response = api.post(Paths.CLAIMS, actor="alice", json=body)
    assert_error(response, 422)


@pytest.mark.parametrize("evidence", ["", "   ", "\n\t"])
def test_create_claim_rejects_empty_evidence(api: Api, scenario, evidence: str):
    body = scenario.claimant("alice").create_payload(evidence)
    response = api.post(Paths.CLAIMS, actor="alice", json=body)
    assert_error(response, 422)


def test_create_claim_without_body_is_422(api: Api):
    response = api.post(Paths.CLAIMS, actor="alice", json=None)
    assert_error(response, 422)


def test_create_claim_for_missing_item_is_404(api: Api, scenario):
    body = scenario.claimant("alice").create_payload(EVIDENCE)
    body["item_id"] = "T-DOES-NOT-EXIST"
    response = api.post(Paths.CLAIMS, actor="alice", json=body)
    assert_error(response, 404)


def test_item_number_is_optional_private_field(api: Api, scenario):
    body = scenario.claimant("alice").create_payload(EVIDENCE)
    body.pop("item_number", None)
    response = api.post(Paths.CLAIMS, actor="alice", json=body)
    expect_status(response, 201)
    claim_id = entity_id(unwrap_entity(response))
    detail = unwrap_entity(api.get_claim(claim_id, "alice"))
    assert detail["item_number"] is None


def test_item_number_is_stored_verbatim_not_verified(api: Api, scenario):
    body = scenario.claimant("alice").create_payload(EVIDENCE)
    body["item_number"] = "THIS-IS-A-PRIVATE-REFERENCE"
    response = api.post(Paths.CLAIMS, actor="alice", json=body)
    expect_status(response, 201)
    claim_id = entity_id(unwrap_entity(response))
    detail = unwrap_entity(api.get_claim(claim_id, "alice"))
    assert detail["item_number"] == "THIS-IS-A-PRIVATE-REFERENCE"


def test_cannot_claim_own_found_listing(api: Api, scenario):
    body = scenario.claimant("alice").create_payload(EVIDENCE)
    body["item_id"] = scenario.found_id
    response = api.post(Paths.CLAIMS, actor="finder", json=body)
    assert_error(response, 422)


def test_cannot_claim_a_lost_listing(api: Api, scenario):
    body = scenario.claimant("alice").create_payload(EVIDENCE)
    body["item_id"] = scenario.claimant("alice").lost_item_id
    response = api.post(Paths.CLAIMS, actor="alice", json=body)
    assert_error(response, 422)


def test_unknown_claim_is_404(api: Api):
    response = api.get_claim(987654321, "alice")
    assert_error(response, 404)
