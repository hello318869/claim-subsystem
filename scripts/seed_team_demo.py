"""Add sample posts for the /team demo without replacing existing data."""

import argparse
import os
import sys
from datetime import timedelta
from pathlib import Path

from sqlalchemy.engine import make_url

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.clock import to_db, utcnow
from app.config import get_settings
from app.db import session_scope
from app.team.demo import DemoPost


def main() -> None:
    parser = argparse.ArgumentParser(description="Add sample posts to the isolated team demo")
    parser.add_argument("--database", choices=("dev", "test"), default="dev")
    args = parser.parse_args()
    os.environ["APP_ENV"] = args.database
    settings = get_settings()
    url = make_url(settings.database_url)
    if (
        not settings.demo_mode or url.get_backend_name() != "mysql"
        or url.host not in {"localhost", "127.0.0.1", "::1"} or url.port != 33307
        or url.database != f"claim_{args.database}"
    ):
        raise SystemExit("Seed requires demo mode and the isolated 33307 database")

    now = to_db(utcnow())
    samples = (
        ("TEAM-DEMO-L01", "lost", "蓝色水杯", "alice", "library", "图书馆", 6),
        ("TEAM-DEMO-L02", "lost", "蓝色水杯带贴纸", "outsider", "library", "图书馆", 5),
        ("TEAM-DEMO-F01", "found", "蓝色水杯", "finder", "library", "图书馆", 4),
        ("TEAM-DEMO-F02", "found", "水杯放在前台", "bob", "gym", "体育馆", 3),
    )
    with session_scope() as session:
        for post_id, post_type, title, publisher, location_id, location_name, hours_ago in samples:
            if session.get(DemoPost, post_id) is None:
                session.add(DemoPost(
                    id=post_id, post_type=post_type, title=title, publisher_id=publisher,
                    category_id="daily", category_name="日用品", campus_id="main", campus_name="主校区",
                    location_id=location_id, location_name=location_name, status="open",
                    occurred_at=now - timedelta(hours=hours_ago), created_at=now, updated_at=now,
                ))
    print(f"Team demo posts ready in {url.database}")


if __name__ == "__main__":
    main()
