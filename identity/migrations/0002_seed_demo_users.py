"""Seed the fixed demo identities used by ``web/team.html`` and the contract tests.

These are synthetic accounts, not real students: no password, no campus binding.  They exist
only because member A's account module is not connected yet.
"""

from __future__ import annotations

from django.db import migrations
from django.utils import timezone

DEMO_USERS = (
    # id, username, nickname, is_campus_verified, verification_mode
    ("alice", "alice", "小林", True, "demo"),
    ("bob", "bob", "小周", True, "demo"),
    ("finder", "finder", "小陈", True, "demo"),
    ("outsider", "outsider", "访客", False, None),
)


def seed_demo_users(apps, schema_editor):
    DemoUser = apps.get_model("identity", "DemoUser")
    now = timezone.now()
    for user_id, username, nickname, verified, mode in DEMO_USERS:
        DemoUser.objects.get_or_create(
            id=user_id,
            defaults={
                "username": username,
                "nickname": nickname,
                "bio": "",
                "is_campus_verified": verified,
                "verification_mode": mode,
                "created_at": now,
                "updated_at": now,
            },
        )


def remove_demo_users(apps, schema_editor):
    DemoUser = apps.get_model("identity", "DemoUser")
    DemoUser.objects.filter(id__in=[row[0] for row in DEMO_USERS]).delete()


class Migration(migrations.Migration):
    dependencies = [("identity", "0001_initial")]

    operations = [migrations.RunPython(seed_demo_users, remove_demo_users)]
