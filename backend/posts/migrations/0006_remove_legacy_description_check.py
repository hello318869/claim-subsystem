"""Preserve stored descriptions and reconcile databases that ran the original 0005."""

from django.db import migrations, models

CHECK_NAME = "ck_post_description_length"


def remove_legacy_description_check(apps, schema_editor):
    post = apps.get_model("posts", "Post")
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        constraints = connection.introspection.get_constraints(cursor, post._meta.db_table)

    # Only older installations of 0005 have this physical constraint. The migration state
    # already omits it, which also gives SQLite the right state for rebuilding the table.
    if constraints.get(CHECK_NAME, {}).get("check"):
        constraint = models.CheckConstraint(condition=models.Q(), name=CHECK_NAME)
        schema_editor.remove_constraint(post, constraint)


class Migration(migrations.Migration):
    dependencies = [("posts", "0005_alter_post_description_and_more")]

    operations = [
        migrations.RunPython(
            remove_legacy_description_check,
            reverse_code=migrations.RunPython.noop,
            atomic=False,
        ),
    ]
