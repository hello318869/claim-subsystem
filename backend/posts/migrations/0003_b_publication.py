import django.db.models.deletion
from django.db import migrations, models

import posts.models


class Migration(migrations.Migration):
    dependencies = [("posts", "0002_seed_dictionaries")]

    operations = [
        # Keep the physical publisher_id column and all its values while removing the
        # foreign key to the demo-only table. A now supplies real account IDs too.
        migrations.AlterField(
            model_name="post", name="publisher",
            field=models.CharField(db_column="publisher_id", db_index=True, max_length=64),
        ),
        migrations.RemoveIndex(model_name="post", name="ix_posts_publisher"),
        migrations.RenameField(model_name="post", old_name="publisher", new_name="publisher_id"),
        migrations.AddIndex(
            model_name="post", index=models.Index(fields=["publisher_id", "-created_at"], name="ix_posts_publisher"),
        ),
        migrations.AlterField(
            model_name="post", name="id",
            field=models.CharField(default=posts.models.new_post_id, max_length=64, primary_key=True, serialize=False),
        ),
        migrations.AddField(
            model_name="post", name="location_detail", field=models.CharField(blank=True, default="", max_length=100),
        ),
        migrations.AddField(
            model_name="post", name="handover_note", field=models.CharField(blank=True, max_length=200, null=True),
        ),
        migrations.AddField(
            model_name="post", name="request_id", field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.AddConstraint(
            model_name="post",
            constraint=models.UniqueConstraint(fields=("publisher_id", "request_id"), name="uniq_post_publisher_request"),
        ),
        migrations.CreateModel(
            name="PostImage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("owner_id", models.CharField(db_index=True, max_length=64)),
                ("file", models.FileField(max_length=255, storage=posts.models.PrivateImageStorage(), upload_to="post-images/")),
                ("mime_type", models.CharField(max_length=32)),
                ("size_bytes", models.PositiveIntegerField()),
                ("sort_order", models.PositiveIntegerField(default=0)),
                ("alt_text", models.CharField(max_length=100)),
                ("is_public", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("post", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                           related_name="images", to="posts.post")),
            ],
            options={"ordering": ["sort_order", "id"]},
        ),
    ]
