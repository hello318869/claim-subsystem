"""V1.0.1 regression: same-second message pagination and cursor isolation."""

from __future__ import annotations

import uuid

from claimtest.api import (
    Api,
    assert_error,
    entity_id,
    message_id,
    message_page,
    unwrap_entity,
)


def _new_claim(api: Api, scenario, actor: str = "alice") -> str:
    return str(entity_id(unwrap_entity(api.create_claim(scenario, actor))))


def _ids(items) -> list[str]:
    return [str(message_id(item)) for item in items]


def test_same_second_60_messages_paginate_without_loss_or_duplicates(
    api: Api, scenario, db_tools
):
    claim_id = _new_claim(api, scenario)
    expected = set(db_tools.insert_messages(claim_id, 60))
    assert len(expected) == 60

    seen: list[str] = []
    cursor: object = 0
    pages = 0
    while True:
        response = api.messages(claim_id, "alice", after=cursor, limit=20)
        items, next_after = message_page(response)
        seen.extend(_ids(items))
        pages += 1
        assert pages <= 10, "pagination did not terminate"
        if next_after is None:
            break
        assert str(next_after) != str(cursor), "next_after did not advance"
        cursor = next_after

    assert len(seen) == 60, f"lost messages: collected {len(seen)} of 60"
    assert len(set(seen)) == 60, "duplicate messages across pages"
    assert set(seen) == expected
    assert db_tools.count_messages(claim_id) == 60


def test_foreign_and_illegal_cursors_do_not_leak_other_conversation(
    api: Api, scenario, db_tools
):
    alice_claim = _new_claim(api, scenario, "alice")
    bob_claim = _new_claim(api, scenario, "bob")
    alice_ids = set(db_tools.insert_messages(alice_claim, 8))
    bob_ids = set(db_tools.insert_messages(bob_claim, 5))
    bob_cursor = next(iter(bob_ids))

    foreign = api.messages(alice_claim, "alice", after=bob_cursor, limit=50)
    if foreign.status_code == 200:
        items, _next = message_page(foreign)
        returned = set(_ids(items))
        assert returned <= alice_ids
        assert returned.isdisjoint(bob_ids)
    else:
        assert_error(foreign, (400, 404, 422))

    illegal = api.messages(
        alice_claim, "alice", after=str(uuid.uuid4()), limit=50
    )
    if illegal.status_code == 200:
        items, _next = message_page(illegal)
        returned = set(_ids(items))
        assert returned <= alice_ids
        assert returned.isdisjoint(bob_ids)
    else:
        assert_error(illegal, (400, 404, 422))
