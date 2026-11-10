"""Run A's real sessions, B's posts and C's claims through one API."""

from datetime import timedelta
from hashlib import sha256
from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from users.models import DemoIdentity

pytestmark = pytest.mark.django_db
BASE = "/api/v1"
PASSWORD = "local-test-password"
BINDING_CODE = "test-binding-code"


def result(response, expected=200):
    assert response.status_code == expected, response.content
    payload = response.json()
    assert payload["code"] == "OK", payload
    return payload["data"]


def create_account(username, student_no=None):
    client = APIClient()
    credentials = {"username": username, "password": PASSWORD}
    registered = result(client.post(f"{BASE}/auth/register", {**credentials, "nickname": username}), 201)
    signed_in = result(client.post(f"{BASE}/auth/login", credentials))
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {signed_in['access_token']}")
    if student_no:
        DemoIdentity.objects.create(
            campus_id="main",
            student_no=student_no,
            code_digest=sha256(BINDING_CODE.encode()).hexdigest(),
        )
        result(client.post(f"{BASE}/users/me/campus-binding", {
            "campus_id": "main", "student_no": student_no, "binding_code": BINDING_CODE,
        }), 201)
    return client, registered["id"]


def publish(client, post_type, hours_ago, **overrides):
    payload = {
        "post_type": post_type,
        "title": "蓝色保温杯",
        "description": "杯身有贴纸，照片用于确认外观。",
        "category_id": "daily",
        "location_id": "library",
        "occurred_at": (timezone.now() - timedelta(hours=hours_ago)).isoformat(),
        "handover_note": "在图书馆一楼交接" if post_type == "found" else None,
        **overrides,
    }
    return result(client.post(f"{BASE}/posts", payload), 201)


def apply(client, post_id):
    return result(client.post(f"{BASE}/claims", {
        "post_id": post_id, "verification_text": "杯底有一道细划痕和一个蓝色标记。",
    }), 201)


@override_settings(RATE_LIMIT_ENABLED=False)
def test_real_accounts_publish_match_and_complete_handover(reference_data, settings, tmp_path):
    settings.PRIVATE_MEDIA_ROOT = tmp_path
    finder, finder_id = create_account("groupfinder", "99000001")
    owner, owner_id = create_account("groupowner", "99000002")

    image = BytesIO()
    Image.new("RGB", (8, 8), "blue").save(image, "PNG")
    uploaded = result(finder.post(f"{BASE}/post-images", {
        "file": SimpleUploadedFile("cup.png", image.getvalue(), content_type="image/png"),
        "alt_text": "蓝色杯子外观照片",
    }, format="multipart"), 201)
    assert APIClient().get(uploaded["url"]).status_code == 404

    lost = publish(owner, "lost", 2)
    found = publish(finder, "found", 1, image_ids=[uploaded["id"]])
    assert found["publisher"]["id"] == finder_id
    assert found["cover_image"]["id"] == uploaded["id"]
    public_image = APIClient().get(uploaded["url"])
    assert public_image.status_code == 200
    assert b"".join(public_image.streaming_content) == image.getvalue()
    assert result(finder.get(f"{BASE}/users/me/posts"))["items"][0]["id"] == found["id"]

    matches = result(owner.get(f"{BASE}/posts/{lost['id']}/matches"))
    assert [item["post"]["id"] for item in matches["items"]] == [found["id"]]
    claim = apply(owner, found["id"])
    assert claim["applicant"]["id"] == owner_id
    assert claim["publisher"]["id"] == finder_id
    assert claim["status"] == "pending"
    claim_url = f"{BASE}/claims/{claim['id']}"
    result(owner.post(f"{claim_url}/messages", {"content": "可在图书馆门口见面。"}), 201)
    assert len(result(finder.get(f"{claim_url}/messages"))["items"]) == 1

    assert result(finder.post(f"{claim_url}/accept", {}))["post"]["status"] == "in_handover"
    assert result(owner.post(f"{claim_url}/confirm-handover", {}))["status"] == "accepted"
    assert result(finder.post(f"{claim_url}/confirm-handover", {}))["status"] == "completed"
    assert result(owner.get(f"{BASE}/posts/{found['id']}"))["status"] == "completed"
    assert finder.post(f"{BASE}/posts/{found['id']}/reopen", {}).status_code == 409
    result(owner.post(f"{BASE}/auth/logout", {}))
    assert owner.get(claim_url).status_code == 401


@override_settings(RATE_LIMIT_ENABLED=False)
def test_post_withdrawal_closes_real_account_claim(reference_data):
    owner, _ = create_account("groupvisitor")
    finder, _ = create_account("groupclaimer", "99000003")
    lost = publish(owner, "lost", 2)
    claim = apply(finder, lost["id"])
    assert result(owner.post(f"{BASE}/posts/{lost['id']}/withdraw", {}))["status"] == "withdrawn"
    assert finder.get(f"{BASE}/posts/{lost['id']}").status_code == 404
    closed = result(finder.get(f"{BASE}/claims/{claim['id']}"))
    assert (closed["status"], closed["close_reason"]) == ("closed", "post_withdrawn")
    assert result(owner.post(f"{BASE}/posts/{lost['id']}/restore", {}))["status"] == "open"
    assert result(finder.get(f"{BASE}/claims/{claim['id']}"))["status"] == "closed"


@override_settings(RATE_LIMIT_ENABLED=False, DEMO_MODE=False)
def test_disabled_demo_mode_rejects_existing_demo_binding_code(reference_data):
    user, _ = create_account("groupdisabled")
    DemoIdentity.objects.create(
        campus_id="main", student_no="99000004", code_digest=sha256(BINDING_CODE.encode()).hexdigest(),
    )
    denied = user.post(f"{BASE}/users/me/campus-binding", {
        "campus_id": "main", "student_no": "99000004", "binding_code": BINDING_CODE,
    })
    assert denied.status_code == 403
    assert result(user.get(f"{BASE}/users/me"))["is_campus_verified"] is False
