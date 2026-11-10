"""Fixed dictionary rows (contract §3.4): one campus, categories and locations.

There is no dictionary management UI in the first version; these ids are shared with the other
two subsystems and must not be re-used for a different meaning.
"""

from __future__ import annotations

from django.db import migrations

CAMPUSES = (("main", "主校区"),)

CATEGORIES = (
    ("keys", "钥匙", 1),
    ("daily", "日用品", 2),
    ("books", "书籍", 3),
    ("electronics", "电子产品", 4),
    ("cards", "证件", 5),
    ("clothing", "衣物", 6),
    ("other", "其他", 7),
)

LOCATIONS = (
    ("library", "main", "图书馆", 1),
    ("gym", "main", "体育馆", 2),
    ("canteen", "main", "食堂", 3),
    ("teaching", "main", "教学楼", 4),
)


def seed_dictionaries(apps, schema_editor):
    Campus = apps.get_model("posts", "Campus")
    Category = apps.get_model("posts", "Category")
    Location = apps.get_model("posts", "Location")

    for campus_id, name in CAMPUSES:
        Campus.objects.get_or_create(id=campus_id, defaults={"name": name})
    for category_id, name, sort_order in CATEGORIES:
        Category.objects.get_or_create(
            id=category_id, defaults={"name": name, "sort_order": sort_order}
        )
    for location_id, campus_id, name, sort_order in LOCATIONS:
        Location.objects.get_or_create(
            id=location_id,
            defaults={"campus_id": campus_id, "name": name, "sort_order": sort_order},
        )


def remove_dictionaries(apps, schema_editor):
    Campus = apps.get_model("posts", "Campus")
    Category = apps.get_model("posts", "Category")
    Location = apps.get_model("posts", "Location")
    Location.objects.filter(id__in=[row[0] for row in LOCATIONS]).delete()
    Category.objects.filter(id__in=[row[0] for row in CATEGORIES]).delete()
    Campus.objects.filter(id__in=[row[0] for row in CAMPUSES]).delete()


class Migration(migrations.Migration):
    dependencies = [("posts", "0001_initial")]

    operations = [migrations.RunPython(seed_dictionaries, remove_dictionaries)]
