"""Claim conversation: send and cursor-based incremental read (§6.2)."""

from __future__ import annotations

import pytest

from claims.models import ClaimMessage
from tests.support import PROOF, RIVAL_PROOF, accept_claim, apply_claim

pytestmark = pytest.mark.django_db


def assert_error(response, status: int, code: str) -> dict:
    assert response.status_code == status, response.content
    body = response.json()
    assert body["code"] == code, body
    return body


def test_send_message_returns_message_view(actors, make_post):
    post = make_post()
    claim_id = apply_claim(actors, post.id, "alice")

    response = actors["alice"].post(
        f"/claims/{claim_id}/messages", {"content": "我什么时候方便来取？"}
    )
    assert response.status_code == 201, response.content
    data = response.json()["data"]
    assert data["claim_id"] == claim_id
    assert data["sender_id"] == "alice"
    assert data["content"] == "我什么时候方便来取？"
    assert data["created_at"].endswith("Z")
    assert data["sender"] == {
        "id": "alice",
        "nickname": "小林",
        "is_campus_verified": True,
        "verification_mode": "demo",
    }
    assert isinstance(data["id"], str)


def test_both_parties_can_send_while_pending_and_accepted(actors, make_post):
    post = make_post()
    claim_id = apply_claim(actors, post.id, "alice")

    assert actors["finder"].post(
        f"/claims/{claim_id}/messages", {"content": "请说明杯子颜色。"}
    ).status_code == 201
    assert accept_claim(actors, claim_id, "finder", "特征相符").status_code == 200
    assert actors["alice"].post(
        f"/claims/{claim_id}/messages", {"content": "明天下午来取可以吗？"}
    ).status_code == 201
    assert ClaimMessage.objects.filter(claim_id=claim_id).count() == 2


def test_outsider_cannot_send_or_read(actors, make_post):
    post = make_post()
    claim_id = apply_claim(actors, post.id, "alice")
    actors["alice"].post(f"/claims/{claim_id}/messages", {"content": "私密内容"})

    assert_error(
        actors["bob"].post(f"/claims/{claim_id}/messages", {"content": "我也来问问"}),
        404,
        "NOT_FOUND",
    )
    response = actors["bob"].get(f"/claims/{claim_id}/messages")
    assert_error(response, 404, "NOT_FOUND")
    assert "私密内容" not in response.content.decode()


@pytest.mark.parametrize("terminal", ("rejected", "cancelled", "closed"))
def test_terminal_claims_are_read_only(actors, make_post, terminal):
    post = make_post()
    claim_id = apply_claim(actors, post.id, "alice")
    if terminal == "rejected":
        actors["finder"].post(f"/claims/{claim_id}/reject", {"decision_note": "特征不符"})
    elif terminal == "cancelled":
        actors["alice"].post(f"/claims/{claim_id}/cancel")
    else:
        ClaimMessage.objects.create(claim_id=claim_id, sender_id="alice", content="历史消息")
        from claims.models import Claim

        Claim.objects.filter(pk=claim_id).update(status="closed", close_reason="post_withdrawn")

    assert_error(
        actors["alice"].post(f"/claims/{claim_id}/messages", {"content": "补充说明"}),
        409,
        "STATE_CONFLICT",
    )
    listing = actors["alice"].get(f"/claims/{claim_id}/messages")
    assert listing.status_code == 200


@pytest.mark.parametrize("content", ("", "   ", "字" * 1001))
def test_message_content_length_is_enforced(actors, make_post, content):
    post = make_post()
    claim_id = apply_claim(actors, post.id, "alice")
    body = assert_error(
        actors["alice"].post(f"/claims/{claim_id}/messages", {"content": content}),
        400,
        "VALIDATION_ERROR",
    )
    assert "content" in body["errors"]


def test_contact_information_is_rejected(actors, make_post):
    post = make_post()
    claim_id = apply_claim(actors, post.id, "alice")
    body = assert_error(
        actors["alice"].post(
            f"/claims/{claim_id}/messages", {"content": "我电话 13800138000"}
        ),
        400,
        "VALIDATION_ERROR",
    )
    assert "content" in body["errors"]


def test_item_numbers_are_allowed(actors, make_post):
    post = make_post()
    claim_id = apply_claim(actors, post.id, "alice")
    response = actors["alice"].post(
        f"/claims/{claim_id}/messages", {"content": "编号 ASSET-2026-0042 的物品在前台"}
    )
    assert response.status_code == 201, response.content


def test_empty_conversation_shape(actors, make_post):
    post = make_post()
    claim_id = apply_claim(actors, post.id, "alice")
    data = actors["alice"].get(f"/claims/{claim_id}/messages").json()["data"]
    assert data == {"items": [], "next_after_id": None, "has_more": False}


def test_incremental_read_uses_ids_in_conversation_order(actors, make_post):
    post = make_post()
    claim_id = apply_claim(actors, post.id, "alice")
    for number in range(1, 6):
        actor = "alice" if number % 2 else "finder"
        response = actors[actor].post(
            f"/claims/{claim_id}/messages", {"content": f"第 {number} 条消息"}
        )
        assert response.status_code == 201

    first = actors["alice"].get(
        f"/claims/{claim_id}/messages", {"limit": 2}
    ).json()["data"]
    assert [item["content"] for item in first["items"]] == ["第 1 条消息", "第 2 条消息"]
    assert first["has_more"] is True
    assert first["next_after_id"] == first["items"][-1]["id"]

    second = actors["alice"].get(
        f"/claims/{claim_id}/messages", {"limit": 2, "after_id": first["next_after_id"]}
    ).json()["data"]
    assert [item["content"] for item in second["items"]] == ["第 3 条消息", "第 4 条消息"]
    assert second["has_more"] is True

    third = actors["alice"].get(
        f"/claims/{claim_id}/messages", {"limit": 2, "after_id": second["next_after_id"]}
    ).json()["data"]
    assert [item["content"] for item in third["items"]] == ["第 5 条消息"]
    assert third["has_more"] is False

    exhausted = actors["alice"].get(
        f"/claims/{claim_id}/messages", {"after_id": third["next_after_id"]}
    ).json()["data"]
    assert exhausted == {
        "items": [],
        "next_after_id": third["next_after_id"],
        "has_more": False,
    }


@pytest.mark.parametrize("after_id", ("abc", "0", "01", "9999999999", "-1"))
def test_invalid_cursor_is_rejected(actors, make_post, after_id):
    post = make_post()
    claim_id = apply_claim(actors, post.id, "alice")
    body = assert_error(
        actors["alice"].get(f"/claims/{claim_id}/messages", {"after_id": after_id}),
        400,
        "VALIDATION_ERROR",
    )
    assert "after_id" in body["errors"]


def test_cursor_from_another_conversation_is_rejected(actors, make_post):
    first_post = make_post()
    second_post = make_post()
    first_claim = apply_claim(actors, first_post.id, "alice")
    second_claim = apply_claim(actors, second_post.id, "alice")
    foreign = actors["alice"].post(
        f"/claims/{second_claim}/messages", {"content": "另一会话的消息"}
    ).json()["data"]["id"]

    body = assert_error(
        actors["alice"].get(f"/claims/{first_claim}/messages", {"after_id": foreign}),
        400,
        "VALIDATION_ERROR",
    )
    assert "after_id" in body["errors"]


@pytest.mark.parametrize("limit", ("0", "101", "abc"))
def test_message_limit_range(actors, make_post, limit):
    post = make_post()
    claim_id = apply_claim(actors, post.id, "alice")
    assert_error(
        actors["alice"].get(f"/claims/{claim_id}/messages", {"limit": limit}),
        400,
        "VALIDATION_ERROR",
    )


def test_message_body_rejects_unknown_fields(actors, make_post):
    post = make_post()
    claim_id = apply_claim(actors, post.id, "alice")
    body = assert_error(
        actors["alice"].post(
            f"/claims/{claim_id}/messages",
            {"content": "正常内容", "sender_id": "finder"},
        ),
        400,
        "VALIDATION_ERROR",
    )
    assert "sender_id" in body["errors"]


def test_messages_are_private_even_when_the_post_is_public(actors, make_post):
    post = make_post()
    claim_id = apply_claim(actors, post.id, "alice")
    actors["finder"].post(f"/claims/{claim_id}/messages", {"content": "只有双方可见的核验答案"})

    public_post = actors["bob"].get(f"/claims/{claim_id}")
    assert public_post.status_code == 404
    assert "核验答案" not in public_post.content.decode()

    # The workbench demo post list stays public and contains no claim data.
    listed = actors["bob"].get("/demo/posts").json()["data"]
    assert PROOF not in str(listed)
    assert RIVAL_PROOF not in str(listed)
