"""Add sample posts for the ``/team`` workbench without replacing existing data.

Replaces the old ``scripts/seed_team_demo.py``.  It refuses to run unless demo mode is on and
the database is the isolated ``claim_dev`` instance on 127.0.0.1:33307.
"""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from posts.models import Location, Post
from posts.services import database_is_isolated

SAMPLES = (
    # id, type, title, publisher, location_id, hours_ago
    ("TEAM-DEMO-L01", "lost", "蓝色水杯", "alice", "library", 6),
    ("TEAM-DEMO-L02", "lost", "蓝色水杯带贴纸", "outsider", "library", 5),
    ("TEAM-DEMO-F01", "found", "蓝色水杯", "finder", "library", 4),
    ("TEAM-DEMO-F02", "found", "水杯放在前台", "bob", "gym", 3),
)


class Command(BaseCommand):
    help = "为 /team 演示补充样例失物/招领信息（幂等）"

    def handle(self, *args, **options):
        if not settings.DEMO_MODE:
            raise CommandError("需要 DEMO_MODE=true 才能写入演示数据")
        if not database_is_isolated():
            raise CommandError("演示数据只能写入 127.0.0.1:33307 的隔离库 claim_dev")

        now = timezone.now()
        created = 0
        for post_id, post_type, title, publisher_id, location_id, hours_ago in SAMPLES:
            if Post.objects.filter(pk=post_id).exists():
                continue
            location = Location.objects.filter(pk=location_id).first()
            if location is None:
                raise CommandError(f"缺少地点字典 {location_id}，请先执行 migrate")
            Post.objects.create(
                id=post_id,
                post_type=post_type,
                title=title,
                description=f"{title}（演示样例，仅用于联调）。",
                category_id="daily",
                location=location,
                publisher_id=publisher_id,
                status="open",
                occurred_at=now - timedelta(hours=hours_ago),
                created_at=now,
                updated_at=now,
            )
            created += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"演示信息已就绪：新建 {created} 条，跳过 {len(SAMPLES) - created} 条。"
            )
        )
