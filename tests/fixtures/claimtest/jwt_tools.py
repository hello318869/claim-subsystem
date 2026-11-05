"""Token tampering helpers for negative authentication tests.

The frozen backend uses ``v1.<base64url(payload)>.<base64url(hmac_sha256)>``;
the helpers also accept a standard three-segment JWT for portability.  Expired
tokens are re-signed with the test-only AUTH_SECRET from ``.env.test``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any


class UnsupportedTokenFormat(RuntimeError):
    """The access token is not a JWT, so an expired token cannot be forged."""


def _b64url_decode(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _split_jwt(token: str) -> tuple[dict[str, Any], dict[str, Any], bytes, str]:
    parts = token.split(".")
    if len(parts) != 3:
        raise UnsupportedTokenFormat("access token is not a three-segment JWT")
    try:
        header = json.loads(_b64url_decode(parts[0]))
        payload = json.loads(_b64url_decode(parts[1]))
    except Exception as exc:  # noqa: BLE001 - format probe only
        raise UnsupportedTokenFormat("access token segments are not JSON") from exc
    if not isinstance(header, dict) or not isinstance(payload, dict):
        raise UnsupportedTokenFormat("JWT header/payload is not an object")
    return header, payload, parts[2].encode("ascii"), parts[0] + "." + parts[1]


def tamper_signature(token: str) -> str:
    """Return a token whose signature differs by one base64url character."""

    if not token:
        raise ValueError("empty token")
    replacement = "A" if token[-1] != "A" else "B"
    return token[:-1] + replacement


def _reforge_v1(token: str, auth_secret: str, *, expires_at: int) -> str:
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != "v1":
        raise UnsupportedTokenFormat("token is not the v1 signed format")
    try:
        payload = json.loads(_b64url_decode(parts[1]))
    except Exception as exc:  # noqa: BLE001
        raise UnsupportedTokenFormat("v1 payload is not JSON") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("sub"), str):
        raise UnsupportedTokenFormat("v1 payload lacks sub")
    payload["exp"] = int(expires_at)
    payload_b64 = _b64url_encode(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    )
    signature = hmac.new(
        auth_secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256
    ).digest()
    return f"v1.{payload_b64}.{_b64url_encode(signature)}"


def _reforge_token(token: str, auth_secret: str, *, expires_at: int) -> str:
    if token.startswith("v1."):
        return _reforge_v1(token, auth_secret, expires_at=expires_at)
    header, payload, _signature, _signing_input = _split_jwt(token)
    algorithm = str(header.get("alg", "HS256")).upper()
    if algorithm not in {"HS256", "HS384", "HS512"}:
        raise UnsupportedTokenFormat(f"unsupported JWT algorithm {algorithm!r}")

    now = int(time.time())
    payload["exp"] = int(expires_at)
    payload["iat"] = min(int(payload.get("iat", now)), int(expires_at) - 1)
    if "nbf" in payload:
        payload["nbf"] = min(int(payload["nbf"]), int(expires_at) - 1)

    encoded_header = _b64url_encode(
        json.dumps(header, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    )
    encoded_payload = _b64url_encode(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    )
    signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
    digestmod = {
        "HS256": hashlib.sha256,
        "HS384": hashlib.sha384,
        "HS512": hashlib.sha512,
    }[algorithm]
    signature = hmac.new(
        auth_secret.encode("utf-8"), signing_input, digestmod
    ).digest()
    return signing_input.decode("ascii") + "." + _b64url_encode(signature)


def forge_expired_token(token: str, auth_secret: str, *, seconds_ago: int = 120) -> str:
    """Re-sign a JWT with an exp in the past, using the test-only secret."""

    return _reforge_token(
        token, auth_secret, expires_at=int(time.time()) - int(seconds_ago)
    )


def forge_future_token(token: str, auth_secret: str, *, seconds_ahead: int = 300) -> str:
    """Re-sign a valid future token, to prove the secret/signature is understood."""

    return _reforge_token(
        token, auth_secret, expires_at=int(time.time()) + int(seconds_ahead)
    )
