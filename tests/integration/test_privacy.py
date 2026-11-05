"""Cross-surface privacy checks: no identity keys in any DTO."""

from __future__ import annotations

from claimtest.api import (
    Api,
    Paths,
    entity_id,
    expect_status,
    json_object,
    message_items,
    unwrap_entity,
    unwrap_items,
)
from claimtest.privacy import assert_no_identity_fields


def test_listing_claim_and_message_surfaces_hide_identity(api: Api, scenario):
    claim_id = entity_id(unwrap_entity(api.create_claim(scenario, "alice")))
    expect_status(api.approve(claim_id, "finder"), 200)

    listing_response = api.get(Paths.listing(scenario.found_id), actor="alice")
    expect_status(listing_response, 200)
    assert_no_identity_fields(
        unwrap_entity(listing_response), context="listing detail"
    )

    page_response = api.get(
        Paths.LISTINGS,
        actor="alice",
        params={"kind": "found", "page": 1, "page_size": 20},
    )
    expect_status(page_response, 200)
    assert_no_identity_fields(json_object(page_response), context="listing page")

    claim_response = api.get_claim(claim_id, "alice")
    expect_status(claim_response, 200)
    claim_view = unwrap_entity(claim_response)
    assert_no_identity_fields(claim_view, context="claim detail")
    assert any(key in claim_view for key in ("role", "my_role", "viewer_role"))

    send = api.send_message(claim_id, "alice", "我只在会话里说物品细节。")
    expect_status(send, 201)
    messages = message_items(api.messages(claim_id, "finder", after=0))
    for message in messages:
        assert_no_identity_fields(message, context="message")


def test_claim_list_page_hides_identity(api: Api, scenario):
    api.create_claim(scenario, "alice")
    response = api.get(
        Paths.CLAIMS, actor="alice", params={"page": 1, "page_size": 20}
    )
    expect_status(response, 200)
    payload = json_object(response)
    assert unwrap_items(payload)
    assert_no_identity_fields(payload, context="claim list page")
