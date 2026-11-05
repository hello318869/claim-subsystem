"""Seed independent test scenarios and the matching dataset into claim_test.

This is test-owned tooling; it never touches claim_dev and only deletes rows whose
item_id starts with the two test prefixes ``T-IT-`` or ``T-M-`` (plus the claims
and idempotency rows that belong to them).

Usage:
    python tests/fixtures/seed_test_world.py
    python tests/fixtures/seed_test_world.py --scenarios 80

Writes ``tests/fixtures/seed-world.json`` used by tests/conftest.py.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "fixtures"))

from claimtest.env import TEST_DB_NAME, load_test_env  # noqa: E402

PREFIX = "T-IT-"
MATCH_PREFIX = "T-M-"
MANIFEST = ROOT / "tests" / "fixtures" / "seed-world.json"
MATCH_FIXTURE = ROOT / "tests" / "fixtures" / "matching-v1.json"

SCENARIO_CATEGORIES = ("bag", "cup", "card", "electronics", "clothing")


def _clean(session) -> None:
    from sqlalchemy import delete, or_, select

    from app.models import (
        AuditEvent,
        Claim,
        HandoverCode,
        IdempotencyRecord,
        ItemApproval,
        ListingSnapshot,
        Message,
    )

    item_like = [PREFIX + "%", MATCH_PREFIX + "%"]
    claim_ids = list(
        session.execute(
            select(Claim.id).where(or_(*[Claim.item_id.like(p) for p in item_like]))
        ).scalars()
    )
    if claim_ids:
        session.execute(delete(Message).where(Message.claim_id.in_(claim_ids)))
        session.execute(delete(HandoverCode).where(HandoverCode.claim_id.in_(claim_ids)))
        session.execute(delete(AuditEvent).where(AuditEvent.claim_id.in_(claim_ids)))
        session.execute(delete(Claim).where(Claim.id.in_(claim_ids)))
    session.execute(
        delete(ItemApproval).where(or_(*[ItemApproval.item_id.like(p) for p in item_like]))
    )
    session.execute(
        delete(ListingSnapshot).where(
            or_(*[ListingSnapshot.item_id.like(p) for p in item_like])
        )
    )
    session.execute(
        delete(AuditEvent).where(or_(*[AuditEvent.item_id.like(p) for p in item_like]))
    )
    # Idempotency rows are test-local and would otherwise leak across reruns.
    session.execute(
        delete(IdempotencyRecord).where(
            IdempotencyRecord.user_id.in_(("alice", "bob", "finder", "outsider"))
        )
    )


def _listing(item_id, kind, title, category, location, description, owner, occurred_at, origin):
    from app.clock import to_db
    from app.models import ListingSnapshot

    return ListingSnapshot(
        item_id=item_id,
        kind=kind,
        title=title,
        category=category,
        location=location,
        description=description,
        status="published",
        publisher_user_id=owner,
        origin=origin,
        occurred_at=to_db(occurred_at),
        synced_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )


def _seed_scenarios(session, count: int, now: datetime) -> list[dict]:
    scenarios: list[dict] = []
    for index in range(1, count + 1):
        sid = f"s{index:02d}"
        found_id = f"{PREFIX}{sid.upper()}-F"
        lost_a = f"{PREFIX}{sid.upper()}-LA"
        lost_b = f"{PREFIX}{sid.upper()}-LB"
        category = SCENARIO_CATEGORIES[(index - 1) % len(SCENARIO_CATEGORIES)]
        location = f"IT测试地点{index % 7}"
        keyword = f"测试物品{index:03d} 蓝色水杯 划痕"
        found_at = now - timedelta(days=2, minutes=index)
        lost_at = now - timedelta(days=3, minutes=index)
        session.add(
            _listing(
                found_id,
                "found",
                f"测试招领物品{index:03d}",
                category,
                location,
                f"招领：{keyword}，编号 IT-{index:03d}",
                "finder",
                found_at,
                "itest",
            )
        )
        session.add(
            _listing(
                lost_a,
                "lost",
                f"测试失物A{index:03d}",
                category,
                location,
                f"丢失：{keyword}，失主 alice",
                "alice",
                lost_at,
                "itest",
            )
        )
        session.add(
            _listing(
                lost_b,
                "lost",
                f"测试失物B{index:03d}",
                category,
                location,
                f"丢失：{keyword}，失主 bob",
                "bob",
                lost_at,
                "itest",
            )
        )
        scenarios.append(
            {
                "id": sid,
                "found_id": found_id,
                "found_title": f"测试招领物品{index:03d}",
                "claimants": {
                    "alice": {
                        "item_id": found_id,
                        "item_number": f"ASSET-IT-{index:03d}-A",
                        "lost_item_id": lost_a,
                    },
                    "bob": {
                        "item_id": found_id,
                        "item_number": f"ASSET-IT-{index:03d}-B",
                        "lost_item_id": lost_b,
                    },
                },
            }
        )
    return scenarios


def _seed_matching(session) -> dict:
    fixture = json.loads(MATCH_FIXTURE.read_text(encoding="utf-8"))
    for record in fixture["found_records"] + fixture["distractors"]:
        session.add(
            _listing(
                f"{MATCH_PREFIX}{record['label']}",
                "found",
                record["title"],
                record["category"],
                record["location"],
                record["description"],
                "finder",
                datetime.fromisoformat(record["occurred_at"]),
                "matcheval",
            )
        )
    for case in fixture["cases"]:
        query = case["query"]
        session.add(
            _listing(
                f"{MATCH_PREFIX}{case['id']}",
                "lost",
                query["title"],
                query["category"],
                query["location"],
                query["description"],
                "alice",
                datetime.fromisoformat(query["occurred_at"]),
                "matcheval",
            )
        )
    return {
        "found_ids": {
            record["label"]: f"{MATCH_PREFIX}{record['label']}"
            for record in fixture["found_records"]
        },
        "lost_item_ids": {
            case["id"]: f"{MATCH_PREFIX}{case['id']}" for case in fixture["cases"]
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenarios", type=int, default=120)
    args = parser.parse_args()
    if args.scenarios < 120:
        raise SystemExit("--scenarios must be at least 120 for the full suite")

    env = load_test_env()
    if env.mysql_dsn()["database"] != TEST_DB_NAME:  # belt and braces
        raise SystemExit("refusing to seed anything except claim_test")

    from app.clock import utcnow
    from app.db import session_scope

    run_id = f"itest-{uuid.uuid4().hex[:12]}"
    now = utcnow()
    with session_scope() as session:
        _clean(session)
        scenarios = _seed_scenarios(session, args.scenarios, now)
        matching = _seed_matching(session)

    manifest = {
        "run_id": run_id,
        "database": TEST_DB_NAME,
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "seed_contract": "claimtest-v1",
        "scenarios": scenarios,
        "matching": matching,
    }
    MANIFEST.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"seeded database={TEST_DB_NAME} scenarios={len(scenarios)} "
        f"matching_found={len(matching['found_ids'])} "
        f"matching_cases={len(matching['lost_item_ids'])} run_id={run_id}"
    )
    print(f"manifest={MANIFEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
