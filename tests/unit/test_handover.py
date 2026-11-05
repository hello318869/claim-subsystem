from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.handover import (
    code_expiry,
    derive_code,
    digest_matches,
    keyed_digest,
    new_nonce,
)

SECRET = "unit-test-secret"


def test_code_is_deterministic_and_eight_digits():
    nonce = new_nonce()
    epoch = 1_800_000_000
    first = derive_code(SECRET, "claim-1", "applicant", nonce, epoch)
    second = derive_code(SECRET, "claim-1", "applicant", nonce, epoch)
    assert first == second
    assert len(first) == 8 and first.isdigit()


def test_two_roles_get_different_codes():
    nonce = new_nonce()
    epoch = 1_800_000_000
    applicant = derive_code(SECRET, "claim-1", "applicant", nonce, epoch)
    finder = derive_code(SECRET, "claim-1", "finder", nonce, epoch)
    assert applicant != finder


def test_nonce_or_expiry_change_changes_code():
    epoch = 1_800_000_000
    base = derive_code(SECRET, "claim-1", "applicant", "a" * 32, epoch)
    assert base != derive_code(SECRET, "claim-1", "applicant", "b" * 32, epoch)
    assert base != derive_code(SECRET, "claim-1", "applicant", "a" * 32, epoch + 1)
    assert base != derive_code(SECRET, "claim-2", "applicant", "a" * 32, epoch)


def test_digest_roundtrip_and_wrong_code():
    code = derive_code(SECRET, "claim-1", "finder", "n" * 32, 1_800_000_000)
    stored = keyed_digest(SECRET, code)
    assert digest_matches(stored, code, SECRET)
    assert not digest_matches(stored, "00000000", SECRET)
    assert not digest_matches(stored, code, "other-secret")


def test_code_expiry_is_capped_by_absolute_deadline():
    now = datetime(2026, 11, 5, 8, 0, tzinfo=timezone.utc)
    assert code_expiry(now, 30, None) == now + timedelta(minutes=30)
    deadline = now + timedelta(minutes=10)
    assert code_expiry(now, 30, deadline) == deadline
