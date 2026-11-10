"""Editing a post accepts the browser payload and preserves note validation."""

import pytest
from rest_framework.test import APIClient

from common.clock import iso
from tests.conftest import make_post, reference_data, tokens  # noqa: F401


_NOTE = "核对杯身特征后在图书馆服务台交接。"


def _patch(post, token, payload):
    return APIClient().patch(
        f"/api/v1/posts/{post.id}", payload, format="json", HTTP_AUTHORIZATION=f"Bearer {token}",
    )


def test_title_edit_accepts_the_browser_payload_with_unchanged_note(make_post, tokens):
    post = make_post(handover_note=_NOTE)
    payload = {
        "title": "图书馆拾到蓝色保温杯",
        "category_id": post.category_id,
        "description": post.description,
        "location_id": post.location_id,
        "location_detail": post.location_detail,
        "occurred_at": iso(post.occurred_at),
        "handover_note": post.handover_note,
    }

    response = _patch(post, tokens["finder"], payload)

    assert response.status_code == 200, response.json()
    assert response.json()["data"]["handover_note"] == _NOTE
    post.refresh_from_db()
    assert (post.title, post.handover_note) == (payload["title"], _NOTE)


def test_found_post_can_change_its_handover_note(make_post, tokens):
    post = make_post(handover_note=_NOTE)
    updated_note = "请到失物招领处核对后领取。"

    response = _patch(post, tokens["finder"], {"handover_note": updated_note})

    assert response.status_code == 200, response.json()
    assert response.json()["data"]["handover_note"] == updated_note
    post.refresh_from_db()
    assert post.handover_note == updated_note


@pytest.mark.parametrize(
    ("post_type", "previous_note", "submitted_note", "error_fragment"),
    [
        ("found", _NOTE, "  ", "招领信息必须填写交接说明"),
        ("lost", None, _NOTE, "失物信息不能填写交接说明"),
    ],
    ids=["found-requires-note", "lost-rejects-note"],
)
def test_handover_note_rules_still_apply(make_post, tokens, post_type, previous_note, submitted_note, error_fragment):
    post = make_post(post_type=post_type, handover_note=previous_note)

    response = _patch(post, tokens["finder"], {"handover_note": submitted_note})

    assert response.status_code == 400
    error = response.json()
    assert error["code"] == "VALIDATION_ERROR"
    assert error_fragment in error["errors"]["handover_note"][0]
    post.refresh_from_db()
    assert post.handover_note == previous_note
