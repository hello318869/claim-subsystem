"""Two-party handover codes.

The code is derived, not stored: ``HMAC(secret, claim|role|nonce|expiry)`` truncated to eight
digits. The database keeps only the nonce, a keyed digest of each side's code, the expiry and
the confirmation flags, so a database dump alone cannot reproduce a code without the server
secret. Because derivation is deterministic, a party can re-fetch its own code after a page
reload; that is the documented recovery mechanism, not a cached plaintext.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

CODE_DIGITS = 8
CODE_MODULUS = 10**CODE_DIGITS
ROLES = ("applicant", "finder")


def new_nonce() -> str:
    return secrets.token_hex(16)


def _message(claim_id: str, role: str, nonce: str, expires_epoch: int) -> bytes:
    return f"v1|{claim_id}|{role}|{nonce}|{expires_epoch}".encode("utf-8")


def derive_code(
    secret: str,
    claim_id: str,
    role: str,
    nonce: str,
    expires_epoch: int,
) -> str:
    if role not in ROLES:
        raise ValueError(f"unknown role: {role}")
    digest = hmac.new(secret.encode("utf-8"), _message(claim_id, role, nonce, expires_epoch), hashlib.sha256).digest()
    value = int.from_bytes(digest[:8], "big") % CODE_MODULUS
    return f"{value:0{CODE_DIGITS}d}"


def keyed_digest(secret: str, code: str) -> str:
    return hmac.new(secret.encode("utf-8"), f"digest|{code}".encode("utf-8"), hashlib.sha256).hexdigest()


def digest_matches(stored_digest: str, candidate_code: str, secret: str) -> bool:
    return hmac.compare_digest(stored_digest, keyed_digest(secret, candidate_code))


def code_expiry(now: datetime, ttl_minutes: int, absolute_deadline: datetime | None) -> datetime:
    expires = now + timedelta(minutes=ttl_minutes)
    if absolute_deadline is not None and expires > absolute_deadline:
        return absolute_deadline
    return expires
