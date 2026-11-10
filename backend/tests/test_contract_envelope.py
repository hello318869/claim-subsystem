"""Transport contract: envelope, authentication, content types, paging and fallbacks (§2)."""

from __future__ import annotations

import pytest
from django.test import override_settings

from tests.support import PROOF, RIVAL_PROOF, apply_claim

pytestmark = pytest.mark.django_db

API = "/api/v1"


def assert_error(response, status: int, code: str) -> dict:
    assert response.status_code == status, response.content
    body = response.json()
    assert set(body) == {"code", "message", "data", "errors"}
    assert body["code"] == code, body
    assert body["data"] is None
    assert isinstance(body["errors"], dict)
    return body


def test_demo_login_returns_token_and_user_self(anonymous):
    response = anonymous.post("/demo/token", {"actor": "alice"})
    assert response.status_code == 200
    body = response.json()
    assert body["code"] == "OK" and body["message"] == "登录成功"
    assert set(body) == {"code", "message", "data"}

    data = body["data"]
    assert data["token_type"] == "Bearer"
    assert isinstance(data["access_token"], str) and data["access_token"]
    assert data["expires_at"].endswith("Z")
    user = data["user"]
    assert user["id"] == "alice"
    assert user["nickname"] == "小林"
    assert user["is_campus_verified"] is True
    assert user["verification_mode"] == "demo"
    assert "password" not in response.content.decode().lower()


def test_demo_login_rejects_unknown_actor(anonymous):
    body = assert_error(anonymous.post("/demo/token", {"actor": "nobody"}), 400, "VALIDATION_ERROR")
    assert "actor" in body["errors"]


def test_demo_login_is_disabled_outside_demo_mode(anonymous):
    with override_settings(DEMO_MODE=False):
        assert_error(anonymous.post("/demo/token", {"actor": "alice"}), 404, "NOT_FOUND")


def test_logout_revokes_only_the_current_token(tokens):
    from identity.services import issue_token
    from tests.conftest import Actor

    first = Actor(tokens["alice"])
    second = Actor(issue_token("alice")["access_token"])
    revoked = first.post("/demo/logout")
    assert revoked.status_code == 200
    assert revoked.json()["data"] is None

    assert_error(first.get("/users/me/claims"), 401, "UNAUTHENTICATED")
    assert second.get("/users/me/claims").status_code == 200


def test_missing_token_is_401_with_bearer_challenge(anonymous):
    response = anonymous.get("/users/me/claims")
    assert_error(response, 401, "UNAUTHENTICATED")
    assert response["WWW-Authenticate"] == "Bearer"


def test_malformed_authorization_header_is_401(anonymous):
    response = anonymous.client.get(f"{API}/users/me/claims", HTTP_AUTHORIZATION="Token abc")
    assert_error(response, 401, "UNAUTHENTICATED")

    blank = anonymous.client.get(f"{API}/users/me/claims", HTTP_AUTHORIZATION="Bearer ")
    assert_error(blank, 401, "UNAUTHENTICATED")


def test_invalid_token_is_401_even_on_public_endpoint(anonymous):
    response = anonymous.client.get(
        f"{API}/demo/posts", HTTP_AUTHORIZATION="Bearer not-a-real-token"
    )
    assert_error(response, 401, "UNAUTHENTICATED")


def test_unknown_api_path_uses_json_envelope(anonymous):
    assert_error(anonymous.get("/does-not-exist"), 404, "NOT_FOUND")
    assert_error(anonymous.client.get(f"{API}/nope"), 404, "NOT_FOUND")


def test_method_not_allowed_uses_json_envelope(actors):
    response = actors["alice"].client.put(
        f"{API}/claims/anything",
        {},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {actors['alice'].token}",
    )
    assert_error(response, 405, "METHOD_NOT_ALLOWED")


def test_unknown_body_field_is_rejected(actors, make_post):
    post = make_post()
    response = actors["alice"].post(
        "/claims",
        {"post_id": post.id, "verification_text": PROOF, "status": "completed"},
    )
    body = assert_error(response, 400, "VALIDATION_ERROR")
    assert "status" in body["errors"]


def test_missing_required_body_field_is_rejected(actors, make_post):
    post = make_post()
    body = assert_error(
        actors["alice"].post("/claims", {"post_id": post.id}), 400, "VALIDATION_ERROR"
    )
    assert "verification_text" in body["errors"]


def test_non_json_content_type_is_415(actors):
    response = actors["alice"].client.post(
        f"{API}/claims",
        data="post_id=x",
        content_type="text/plain",
        HTTP_AUTHORIZATION=f"Bearer {actors['alice'].token}",
    )
    assert_error(response, 415, "UNSUPPORTED_MEDIA_TYPE")


def test_broken_json_is_400(actors):
    response = actors["alice"].client.post(
        f"{API}/claims",
        data='{"post_id": ',
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {actors['alice'].token}",
    )
    assert_error(response, 400, "VALIDATION_ERROR")


@pytest.mark.parametrize(
    "params",
    (
        {"page": "0"},
        {"page": "abc"},
        {"page_size": "0"},
        {"page_size": "101"},
        {"role": "everyone"},
        {"status": "unknown"},
    ),
)
def test_invalid_query_parameters_are_400(actors, params):
    body = assert_error(
        actors["alice"].get("/users/me/claims", params), 400, "VALIDATION_ERROR"
    )
    assert body["errors"]


def test_health_reports_database_and_demo_mode(anonymous):
    response = anonymous.client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["database"] == "ok"
    assert payload["demo_mode"] is True
    assert payload["time"].endswith("Z")


def test_root_redirects_to_the_workbench(anonymous):
    response = anonymous.client.get("/")
    assert response.status_code == 302
    assert response["Location"] == "/team"


def test_actions_accept_an_omitted_or_empty_body(actors, make_post):
    post = make_post()
    claim_id = apply_claim(actors, post.id, "alice")

    # No body and no Content-Type at all (what the workbench sends).
    omitted = actors["alice"].client.generic(
        "POST",
        f"{API}/claims/{claim_id}/cancel",
        HTTP_AUTHORIZATION=f"Bearer {actors['alice'].token}",
    )
    assert omitted.status_code == 200, omitted.content
    assert omitted.json()["data"]["status"] == "cancelled"

    # An explicit empty JSON body is equally valid for another optional-body action.
    other = apply_claim(actors, make_post().id, "alice", RIVAL_PROOF)
    empty = actors["alice"].client.post(
        f"{API}/claims/{other}/cancel",
        data="",
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {actors['alice'].token}",
    )
    assert empty.status_code == 200, empty.content


def test_success_payload_has_no_errors_key(actors):
    response = actors["alice"].get("/users/me/claims")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"code", "message", "data"}
    assert body["data"] == {
        "items": [],
        "page": 1,
        "page_size": 20,
        "total": 0,
        "total_pages": 0,
    }


def test_pagination_metadata(actors, make_post):
    from tests.support import apply_claim

    posts = [make_post() for _ in range(3)]
    for post in posts:
        apply_claim(actors, post.id)

    first = actors["alice"].get("/users/me/claims", {"page_size": 2}).json()["data"]
    assert (first["page"], first["page_size"], first["total"], first["total_pages"]) == (1, 2, 3, 2)
    assert len(first["items"]) == 2

    second = actors["alice"].get("/users/me/claims", {"page": 2, "page_size": 2}).json()["data"]
    assert len(second["items"]) == 1

    beyond = actors["alice"].get("/users/me/claims", {"page": 9}).json()["data"]
    assert beyond["items"] == [] and beyond["total"] == 3
