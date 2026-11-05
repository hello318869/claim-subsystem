"""Idempotency-Key replay, conflicts and key-optional deduplication."""

from __future__ import annotations

import uuid

import pytest

from claimtest.api import (
    Api,
    Paths,
    assert_error,
    entity_id,
    expect_status,
    message_id,
    message_items,
    message_text,
    unwrap_entity,
)
from claimtest.privacy import assert_no_identity_fields

EVIDENCE_ONE = "私有证据：盒盖内侧有星星贴纸。"
EVIDENCE_TWO = "私有证据：盒盖内侧没有任何贴纸。"


def _body(scenario, actor: str = "alice", evidence: str = EVIDENCE_ONE) -> dict:
    return scenario.claimant(actor).create_payload(evidence)


def test_same_key_same_body_replays_same_claim(api: Api, scenario):
    key = f"claim-replay-{uuid.uuid4().hex}"
    first = api.create_claim(
        scenario, "alice", evidence_text=EVIDENCE_ONE, idempotency_key=key
    )
    second = api.create_claim(
        scenario,
        "alice",
        evidence_text=EVIDENCE_ONE,
        idempotency_key=key,
        expect=(200, 201),
    )
    assert entity_id(unwrap_entity(first)) == entity_id(unwrap_entity(second))

    detail = unwrap_entity(api.get_claim(entity_id(unwrap_entity(first)), "alice"))
    assert detail["evidence_text"] == EVIDENCE_ONE
    assert_no_identity_fields(detail, context="replayed claim detail")


def test_same_key_different_body_is_409(api: Api, scenario):
    key = f"claim-conflict-{uuid.uuid4().hex}"
    first = api.create_claim(
        scenario, "alice", evidence_text=EVIDENCE_ONE, idempotency_key=key
    )
    claim_id = entity_id(unwrap_entity(first))

    conflict = api.post(
        Paths.CLAIMS,
        actor="alice",
        json=_body(scenario, evidence=EVIDENCE_TWO),
        idempotency_key=key,
    )
    assert_error(conflict, 409)

    detail = unwrap_entity(api.get_claim(claim_id, "alice"))
    assert detail["evidence_text"] == EVIDENCE_ONE


@pytest.mark.parametrize("key", [None, ""])
def test_missing_or_empty_key_is_allowed_and_deduplicated(api: Api, scenario, db_tools, key):
    first = api.post(
        Paths.CLAIMS,
        actor="alice",
        json=_body(scenario),
        idempotency_key=key,
    )
    expect_status(first, 201)
    claim_id = entity_id(unwrap_entity(first))

    second = api.post(
        Paths.CLAIMS,
        actor="alice",
        json=_body(scenario),
        idempotency_key=key,
    )
    expect_status(second, 200)
    assert entity_id(unwrap_entity(second)) == claim_id
    assert db_tools.count_claims_for_item(scenario.found_id) == 1


def test_message_replay_returns_same_message(api: Api, scenario):
    claim_id = entity_id(unwrap_entity(api.create_claim(scenario, "alice")))
    key = f"message-replay-{uuid.uuid4().hex}"
    text = "请在服务台等我十分钟。"
    first = api.send_message(
        claim_id, "alice", text, idempotency_key=key, expect=(200, 201)
    )
    second = api.send_message(
        claim_id, "alice", text, idempotency_key=key, expect=(200, 201)
    )
    assert message_id(unwrap_entity(first)) == message_id(unwrap_entity(second))

    messages = message_items(api.messages(claim_id, "alice", after=0))
    matches = [item for item in messages if message_text(item) == text]
    assert len(matches) == 1


def test_message_same_key_different_text_is_409(api: Api, scenario):
    claim_id = entity_id(unwrap_entity(api.create_claim(scenario, "alice")))
    key = f"message-conflict-{uuid.uuid4().hex}"
    first = api.send_message(
        claim_id, "alice", "第一条内容", idempotency_key=key, expect=(200, 201)
    )
    assert message_id(unwrap_entity(first))

    conflict = api.post(
        Paths.messages(claim_id),
        actor="alice",
        json={"text": "被篡改的第二条内容"},
        idempotency_key=key,
    )
    assert_error(conflict, 409)

    texts = [
        message_text(item)
        for item in message_items(api.messages(claim_id, "alice", after=0))
    ]
    assert "第一条内容" in texts
    assert "被篡改的第二条内容" not in texts
