"""Exercise both upgrade paths on isolated in-memory migration databases."""

import pytest
from django.db import connections, migrations, models, router
from django.db.migrations.executor import MigrationExecutor
from django.db.models.functions import Length
from django.db.models.lookups import GreaterThanOrEqual, LessThanOrEqual
from django.db.utils import ConnectionHandler
from django.utils import timezone

BEFORE_CHECK = ("posts", "0004_merge_b_locations")
ORIGINAL_CHECK = ("posts", "0005_alter_post_description_and_more")
LATEST = ("posts", "0006_remove_legacy_description_check")
CHECK_NAME = "ck_post_description_length"


@pytest.fixture
def migration_connection(django_db_blocker, monkeypatch):
    alias = "posts_description_migration"
    in_memory = ConnectionHandler({
        "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"},
    })
    monkeypatch.setitem(connections.databases, alias, in_memory.databases["default"])

    # Older data migrations rely on Django's router instead of using the schema editor alias.
    monkeypatch.setattr(router, "db_for_read", lambda *args, **kwargs: alias)
    monkeypatch.setattr(router, "db_for_write", lambda *args, **kwargs: alias)

    def reject_default_connection():
        pytest.fail("The migration regression must stay on its isolated SQLite connection")

    monkeypatch.setattr(connections["default"], "ensure_connection", reject_default_connection)
    with django_db_blocker.unblock():
        connection = connections[alias]
        try:
            yield connection
        finally:
            connection.close()
            del connections[alias]


def _migrate(connection, target):
    return MigrationExecutor(connection).migrate([target]).apps


def _add_post(apps, connection, post_id, description):
    return apps.get_model("posts", "Post").objects.using(connection.alias).create(
        id=post_id,
        publisher_id="legacy-publisher",
        post_type="lost",
        title="存量失物",
        description=description,
        category_id="daily",
        location_id="library",
        occurred_at=timezone.now(),
    )


def _constraints(connection):
    with connection.cursor() as cursor:
        return connection.introspection.get_constraints(cursor, "posts_post")


def test_upgrade_from_0004_preserves_descriptions(migration_connection):
    connection = migration_connection
    old_apps = _migrate(connection, BEFORE_CHECK)
    descriptions = {"blank": "", "short": " 原文\n", "long": "原文😀" * 700 + "\n"}
    for post_id, description in descriptions.items():
        _add_post(old_apps, connection, post_id, description)

    apps = _migrate(connection, LATEST)
    stored = apps.get_model("posts", "Post").objects.using(connection.alias)
    assert dict(stored.values_list("pk", "description")) == descriptions
    assert CHECK_NAME not in _constraints(connection)


def test_upgrade_from_applied_original_0005_drops_only_its_check(migration_connection):
    connection = migration_connection
    old_apps = _migrate(connection, BEFORE_CHECK)
    original = "保留升级前已经存在的描述原文。"
    _add_post(old_apps, connection, "before-0005", original)

    executor = MigrationExecutor(connection)
    length = Length("description")
    executor.loader.get_migration(*ORIGINAL_CHECK).operations.append(
        migrations.AddConstraint(
            model_name="post",
            constraint=models.CheckConstraint(
                condition=GreaterThanOrEqual(length, 10) & LessThanOrEqual(length, 2000),
                name=CHECK_NAME,
            ),
        )
    )
    executor.migrate([ORIGINAL_CHECK])
    assert _constraints(connection)[CHECK_NAME]["check"]

    apps = _migrate(connection, LATEST)
    constraints = _constraints(connection)
    assert CHECK_NAME not in constraints
    assert constraints["uniq_post_publisher_request"]["unique"]
    stored = apps.get_model("posts", "Post").objects.using(connection.alias)
    assert stored.get(pk="before-0005").description == original
    _add_post(apps, connection, "after-0006", "")
    assert stored.get(pk="after-0006").description == ""
