from __future__ import annotations

import time

import pytest

from app.errors import AppError
from app.security import issue_token, verify_token

SECRET = "unit-test-secret-value"


def test_roundtrip_returns_subject():
    token, expires = issue_token("alice", SECRET, ttl_minutes=60)
    payload = verify_token(token, SECRET)
    assert payload["sub"] == "alice"
    assert payload["exp"] == expires


def test_tampered_payload_is_rejected():
    token, _ = issue_token("alice", SECRET, ttl_minutes=60)
    header, payload, signature = token.split(".")
    forged = f"{header}.{payload[:-2]}AA.{signature}"
    with pytest.raises(AppError) as exc:
        verify_token(forged, SECRET)
    assert exc.value.status_code == 401


def test_wrong_secret_is_rejected():
    token, _ = issue_token("alice", SECRET, ttl_minutes=60)
    with pytest.raises(AppError):
        verify_token(token, "another-secret")


def test_expired_token_is_rejected():
    token, _ = issue_token("alice", SECRET, ttl_minutes=1, now_epoch=int(time.time()) - 3600)
    with pytest.raises(AppError) as exc:
        verify_token(token, SECRET)
    assert exc.value.code == "unauthorized"


def test_malformed_token_is_rejected():
    with pytest.raises(AppError):
        verify_token("not-a-token", SECRET)
