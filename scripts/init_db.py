"""Create database tables for the isolated claim_dev / claim_test instance.

Usage (never drops data):
    python scripts/init_db.py                # dev database from .env
    python scripts/init_db.py --database test  # claim_test from .env.test
    python scripts/init_db.py --check        # report missing tables only
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="Create tables in the isolated MySQL instance")
    parser.add_argument("--database", choices=["dev", "test"], default="dev")
    parser.add_argument("--check", action="store_true", help="only report missing tables")
    args = parser.parse_args()

    if args.database == "test":
        os.environ["APP_ENV"] = "test"

    from sqlalchemy import inspect

    from app.config import get_settings
    from app.db import get_engine
    from app.models import Base

    settings = get_settings()
    engine = get_engine()
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    expected = set(Base.metadata.tables)

    if args.check:
        missing = sorted(expected - existing)
        print(f"environment={settings.environment} tables={len(existing)} missing={len(missing)}")
        for name in missing:
            print(f"  missing: {name}")
        return 0 if not missing else 1

    Base.metadata.create_all(engine)
    after = set(inspect(engine).get_table_names())
    print(f"environment={settings.environment} tables={len(after)} created=0 dropped=0")
    for name in sorted(expected):
        print(f"  {'ok' if name in after else 'MISSING'}: {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
