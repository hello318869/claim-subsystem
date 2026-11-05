"""Seed demo snapshots and identities (idempotent, never destructive).

The rows are clearly marked ``origin='demo'``: they are local fixtures, not data from the
other members' services. Suitable for the local demonstration only.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DEMO_FOUND = [
    ("F-1001", "黑色双肩包", "bag", "图书馆二楼", "黑色双肩包，侧袋有一个蓝色水杯", 1),
    ("F-1002", "蓝色保温杯", "cup", "图书馆三楼", "蓝色保温杯，杯身有一道划痕", 2),
    ("F-1003", "校园卡", "card", "第二食堂", "校园卡一张，姓名处已磨损，尾号 37", 3),
    ("F-1004", "白色无线耳机", "electronics", "体育馆东门", "白色无线耳机，充电盒贴有卡通贴纸", 5),
    ("F-1005", "灰色围巾", "clothing", "教学楼 A 座", "灰色针织围巾，末端有小洞", 8),
]

DEMO_LOST = [
    ("L-2001", "黑色双肩包", "bag", "图书馆二楼", "黑色双肩包，内有蓝色水杯和借书卡", 1, "alice"),
    ("L-2002", "蓝色保温杯", "cup", "图书馆三楼", "蓝色保温杯，杯身有划痕", 2, "bob"),
    ("L-2003", "校园卡", "card", "第二食堂", "校园卡，尾号 37", 3, "alice"),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed demo listings into the isolated database")
    parser.add_argument("--database", choices=["dev", "test"], default="dev")
    args = parser.parse_args()
    if args.database == "test":
        os.environ["APP_ENV"] = "test"

    from app.clock import to_db, utcnow
    from app.db import session_scope
    from app.models import ListingSnapshot

    now = utcnow()
    created = 0
    with session_scope() as session:
        existing = {row.item_id for row in session.query(ListingSnapshot).all()}
        for item_id, title, category, location, description, days_ago in DEMO_FOUND:
            if item_id in existing:
                continue
            session.add(
                ListingSnapshot(
                    item_id=item_id,
                    kind="found",
                    title=title,
                    category=category,
                    occurred_at=to_db(now - timedelta(days=days_ago)),
                    location=location,
                    description=description,
                    status="published",
                    publisher_user_id="finder",
                    origin="demo",
                    synced_at=to_db(now),
                )
            )
            created += 1
        for item_id, title, category, location, description, days_ago, owner in DEMO_LOST:
            if item_id in existing:
                continue
            session.add(
                ListingSnapshot(
                    item_id=item_id,
                    kind="lost",
                    title=title,
                    category=category,
                    occurred_at=to_db(now - timedelta(days=days_ago)),
                    location=location,
                    description=description,
                    status="published",
                    publisher_user_id=owner,
                    origin="demo",
                    synced_at=to_db(now),
                )
            )
            created += 1
    print(f"environment={'test' if args.database == 'test' else 'dev'} seeded={created} origin=demo")
    print("demo actors: alice, bob, finder, outsider (POST /v1/demo/token)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
