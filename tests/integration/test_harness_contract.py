"""Offline checks for the test harness itself (no backend, no row creation)."""

from __future__ import annotations

import json

import pytest

from claimtest.clock import ClockSeam, ClockUnavailable
from claimtest.env import PROJECT_ROOT, load_test_env
from claimtest.privacy import PrivacyViolation, assert_no_identity_fields
from claimtest.seed import build_world

pytestmark = pytest.mark.offline

EXAMPLE = PROJECT_ROOT / "tests" / "fixtures" / "seed-world.example.json"


def test_example_seed_manifest_validates_via_adapter():
    raw = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    world = build_world(raw, source="example")
    assert world.database == "claim_test"
    assert len(world.scenarios) == 2
    first = world.take_scenario()
    assert first.claimant("alice").item_number
    assert first.claimant("bob").item_number
    assert first.found_id is not None


def test_clock_seam_only_accepts_claim_test_updates():
    env = load_test_env()
    good = ClockSeam(
        {
            "expire_code_sql": (
                "UPDATE handover_codes SET expires_at = UTC_TIMESTAMP() "
                "WHERE claim_id = %(claim_id)s"
            )
        },
        env,
    )
    assert good.can_expire_code is True

    bad_statements = [
        "DELETE FROM handover_codes WHERE claim_id = %(claim_id)s",
        "UPDATE claim_dev.handover_codes SET expires_at = UTC_TIMESTAMP()",
        "UPDATE handover_codes SET expires_at = UTC_TIMESTAMP(); DROP TABLE x",
        "UPDATE handover_codes SET expires_at = %(evil)s",
    ]
    for statement in bad_statements:
        with pytest.raises(ClockUnavailable):
            ClockSeam({"expire_code_sql": statement}, env)


def test_privacy_detector_flags_identity_but_allows_role():
    with pytest.raises(PrivacyViolation):
        assert_no_identity_fields({"data": {"user_id": 7}})
    with pytest.raises(PrivacyViolation):
        assert_no_identity_fields({"data": [{"ownerId": 7}]})
    with pytest.raises(PrivacyViolation):
        assert_no_identity_fields({"sender": {"email": "x@example.com"}})
    assert_no_identity_fields(
        {"data": {"id": 1, "role": "claimant", "status": "PENDING"}}
    )
