"""Add B's distinct location choices while retaining the existing dictionary IDs."""

from django.db import migrations


def merge_locations(apps, schema_editor):
    Campus = apps.get_model("posts", "Campus")
    Location = apps.get_model("posts", "Location")
    alias = schema_editor.connection.alias
    Campus.objects.using(alias).get_or_create(id="main", defaults={"name": "主校区"})
    locations = Location.objects.using(alias)
    for location_id, name, order in (("playground", "操场", 5), ("dormitory", "宿舍楼", 6)):
        if not locations.filter(campus_id="main", name=name).exists():
            locations.get_or_create(
                id=location_id, defaults={"campus_id": "main", "name": name, "sort_order": order},
            )


class Migration(migrations.Migration):
    dependencies = [("posts", "0003_b_publication")]

    # A published post can reference either new location after deployment.
    operations = [migrations.RunPython(merge_locations, migrations.RunPython.noop)]
