"""Private conversation: participants, cursors, PII hard-block and read-only terminals."""

from __future__ import annotations

import json
import time

import pytest

from claimtest.api import (
    Api,
    Paths,
    assert_error,
    entity_id,
    expect_status,
    json_object,
    message_id,
    message_items,
    message_text,
    unwrap_entity,
)
from claimtest.privacy import PII_CASES, assert_no_identity_fields


def _new_claim(api: Api, scenario) -> object:
    return entity_id(unwrap_entity(api.create_claim(scenario, "alice")))


def test_both_parties_can_exchange_messages(api: Api, scenario):
    claim_id = _new_claim(api, scenario)

    sent = api.send_message(
        claim_id, "alice", "我已经到图书馆一楼服务台，穿灰色外套。"
    )
    sent_entity = unwrap_entity(sent)
    assert message_text(sent_entity) == "我已经到图书馆一楼服务台，穿灰色外套。"
    assert_no_identity_fields(sent_entity, context="posted message")

    finder_sent = api.send_message(claim_id, "finder", "我在服务台，请出示认领编号。")
    assert message_text(unwrap_entity(finder_sent)) == "我在服务台，请出示认领编号。"

    messages = message_items(api.messages(claim_id, "alice", after=0))
    texts = [message_text(item) for item in messages]
    assert "我已经到图书馆一楼服务台，穿灰色外套。" in texts
    assert "我在服务台，请出示认领编号。" in texts
    for item in messages:
        assert_no_identity_fields(item, context="message DTO")


def test_outsider_cannot_read_or_post_messages(api: Api, scenario):
    claim_id = _new_claim(api, scenario)
    assert_error(api.messages(claim_id, "outsider", after=0), 403)
    assert_error(
        api.post(Paths.messages(claim_id), actor="outsider", json={"text": "你好"}),
        403,
    )


def test_after_cursor_is_exclusive(api: Api, scenario):
    claim_id = _new_claim(api, scenario)
    first = unwrap_entity(api.send_message(claim_id, "alice", "第一条消息"))
    time.sleep(1.05)  # message ordering is by created_at; keep the two rows distinct
    second = unwrap_entity(api.send_message(claim_id, "alice", "第二条消息"))
    first_id = message_id(first)
    second_id = message_id(second)

    all_items = message_items(api.messages(claim_id, "alice", after=0))
    all_texts = [message_text(item) for item in all_items]
    assert all_texts.index("第一条消息") < all_texts.index("第二条消息")

    after_first = message_items(api.messages(claim_id, "alice", after=first_id))
    after_first_texts = [message_text(item) for item in after_first]
    assert "第一条消息" not in after_first_texts
    assert "第二条消息" in after_first_texts

    after_second = message_items(api.messages(claim_id, "alice", after=second_id))
    assert after_second == []


def test_pii_in_messages_is_blocked_and_not_stored(api: Api, scenario):
    claim_id = _new_claim(api, scenario)
    for label, value in PII_CASES:
        response = api.post(
            Paths.messages(claim_id),
            actor="alice",
            json={"text": f"我的{label}是 {value}，请联系我"},
        )
        error = assert_error(response, 422)
        guidance = f"{error['message']} {error.get('field', '')}".lower()
        assert any(
            token in guidance
            for token in ("编号", "证据", "隐私", "private", "evidence", "number")
        ), "PII rejection should direct the user to the private claim evidence/number"

    stored = json.dumps(
        message_items(api.messages(claim_id, "alice", after=0)), ensure_ascii=False
    )
    for _label, value in PII_CASES:
        assert value not in stored


@pytest.mark.parametrize("text", ["", "\n\t"])
def test_empty_message_is_422(api: Api, scenario, text: str):
    claim_id = _new_claim(api, scenario)
    response = api.post(Paths.messages(claim_id), actor="alice", json={"text": text})
    assert_error(response, 422)


def test_messages_allowed_after_approval(api: Api, scenario):
    claim_id = _new_claim(api, scenario)
    expect_status(api.approve(claim_id, "finder"), 200)
    api.send_message(claim_id, "alice", "我明天下午三点来取，可以吗？")
    messages = message_items(api.messages(claim_id, "finder", after=0))
    assert any("明天下午三点" in message_text(item) for item in messages)


def test_terminal_claim_messages_are_read_only(api: Api, scenario):
    claim_id = _new_claim(api, scenario)
    api.send_message(claim_id, "alice", "认领编号在私有证据里。")
    expect_status(api.withdraw(claim_id, "alice"), 200)

    read = api.messages(claim_id, "alice", after=0)
    expect_status(read, 200)
    assert message_items(read)

    blocked = api.post(
        Paths.messages(claim_id), actor="alice", json={"text": "还能发吗？"}
    )
    assert_error(blocked, 409)


def test_messages_for_unknown_claim_is_404(api: Api):
    assert_error(api.messages(987654321, "alice", after=0), 404)
