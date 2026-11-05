"""Signed bearer tokens.

Token format: ``v1.<base64url(payload)>.<base64url(hmac_sha256)>``.
Every verification checks the signature first and the ``exp`` claim second.
No third-party JWT library is used, so the check order is explicit and testable.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from app.errors import AppError


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _signature(payload_b64: str, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256).digest()
    return _b64encode(digest)


def issue_token(subject: str, secret: str, *, ttl_minutes: int, now_epoch: int | None = None) -> tuple[str, int]:
    issued = int(now_epoch if now_epoch is not None else time.time())
    expires = issued + ttl_minutes * 60
    payload = {"sub": subject, "iat": issued, "exp": expires}
    payload_b64 = _b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    return f"v1.{payload_b64}.{_signature(payload_b64, secret)}", expires


def verify_token(token: str, secret: str, *, now_epoch: int | None = None) -> dict[str, Any]:
    unauthorized = AppError(401, "unauthorized", "令牌无效或已过期")
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != "v1":
        raise unauthorized

    payload_b64, signature = parts[1], parts[2]
    expected = _signature(payload_b64, secret)
    if not hmac.compare_digest(expected, signature):
        raise unauthorized

    try:
        payload = json.loads(_b64decode(payload_b64))
    except (ValueError, json.JSONDecodeError) as exc:  # pragma: no cover - defensive
        raise unauthorized from exc

    if not isinstance(payload, dict) or not isinstance(payload.get("sub"), str):
        raise unauthorized

    now = int(now_epoch if now_epoch is not None else time.time())
    expires = payload.get("exp")
    if not isinstance(expires, int) or expires <= now:
        raise unauthorized
    return payload
