"""Identity demonstration and bearer-token negative cases."""

from __future__ import annotations

import uuid

import pytest

from claimtest.api import Api, Paths, assert_error, expect_status, json_object
from claimtest.jwt_tools import (
    UnsupportedTokenFormat,
    forge_expired_token,
    forge_future_token,
    tamper_signature,
)

ACTORS = ("alice", "bob", "finder", "outsider")


@pytest.mark.parametrize("actor", ACTORS)
def test_demo_token_returns_signed_bearer_token(api: Api, actor: str):
    response = api.raw(
        "POST",
        Paths.DEMO_TOKEN,
        json={"actor": actor},
        headers={"Idempotency-Key": f"demo-token-{actor}-{uuid.uuid4().hex}"},
    )
    expect_status(response, 200)
    payload = json_object(response)
    assert isinstance(payload.get("token"), str) and payload["token"].startswith("v1.")
    assert payload.get("actor") == actor
    assert isinstance(payload.get("expires_at"), str) and payload["expires_at"].endswith("Z")
    # The contract exposes the demo actor, but never a user_id/publisher_id mapping.
    assert "user_id" not in payload and "publisher_id" not in payload


def test_missing_token_is_401(api: Api):
    response = api.raw("GET", Paths.LISTINGS)
    assert_error(response, 401)


@pytest.mark.parametrize(
    "authorization",
    [
        "Bearer not-a-real-token",
        "Bearer",
        "Token abc.def.ghi",
        "Basic YWxpY2U6cGFzcw==",
    ],
)
def test_invalid_authorization_is_401(api: Api, authorization: str):
    response = api.raw(
        "GET", Paths.LISTINGS, headers={"Authorization": authorization}
    )
    assert_error(response, 401)


def test_tampered_token_is_401(api: Api):
    token = api.token("alice")
    bad = tamper_signature(token)
    assert bad != token
    response = api.raw(
        "GET", Paths.LISTINGS, headers={"Authorization": f"Bearer {bad}"}
    )
    assert_error(response, 401)


def test_expired_but_signed_token_is_401(api: Api, test_env):
    token = api.token("alice")
    try:
        future = forge_future_token(token, test_env.auth_secret)
        expired = forge_expired_token(token, test_env.auth_secret)
    except UnsupportedTokenFormat as exc:
        pytest.skip(f"expired-token case needs the signed v1 token format: {exc}")
    assert future != token and expired != token

    # Prove the secret is really the signing key before interpreting a 401 as expiry.
    control = api.raw(
        "GET", Paths.LISTINGS, headers={"Authorization": f"Bearer {future}"}
    )
    if control.status_code != 200:
        pytest.skip(
            "AUTH_SECRET did not produce an accepted future token; expiry cannot be "
            "isolated from signature/config mismatch"
        )

    response = api.raw(
        "GET", Paths.LISTINGS, headers={"Authorization": f"Bearer {expired}"}
    )
    assert_error(response, 401)


def test_unknown_actor_is_422(api: Api):
    response = api.raw(
        "POST",
        Paths.DEMO_TOKEN,
        json={"actor": "mallory"},
        headers={"Idempotency-Key": f"demo-token-mallory-{uuid.uuid4().hex}"},
    )
    assert_error(response, 422)


def test_missing_actor_is_422(api: Api):
    response = api.raw(
        "POST",
        Paths.DEMO_TOKEN,
        json={},
        headers={"Idempotency-Key": f"demo-token-missing-{uuid.uuid4().hex}"},
    )
    assert_error(response, 422)
