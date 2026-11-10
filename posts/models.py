"""Dictionary and post tables used by the local B adapter.

The contract (§3.4/§3.5) keeps these under member B: campuses, categories, locations and the
lost/found posts themselves.  C never writes them; it reads a post through
``posts.services.get_post_for_claim`` and asks for state changes through
``posts.services.set_handover_state`` (contract §7.3).  When B's real module arrives, only that
service module is replaced.
"""

from __future__ import annotations

from django.db import models
from django.utils import timezone


class Campus(models.Model):
    id = models.CharField(primary_key=True, max_length=64)
    name = models.CharField(max_length=60)

    class Meta:
        verbose_name = "校区"
        verbose_name_plural = "校区"
        ordering = ["id"]

    def __str__(self) -> str:  # pragma: no cover
        return self.name


class Category(models.Model):
    id = models.CharField(primary_key=True, max_length=64)
    name = models.CharField(max_length=60)
    sort_order = models.IntegerField(default=0)

    class Meta:
        verbose_name = "物品类别"
        verbose_name_plural = "物品类别"
        ordering = ["sort_order", "id"]

    def __str__(self) -> str:  # pragma: no cover
        return self.name


class Location(models.Model):
    id = models.CharField(primary_key=True, max_length=64)
    campus = models.ForeignKey(Campus, on_delete=models.PROTECT, related_name="locations")
    name = models.CharField(max_length=60)
    sort_order = models.IntegerField(default=0)

    class Meta:
        verbose_name = "位置"
        verbose_name_plural = "位置"
        ordering = ["sort_order", "id"]

    def __str__(self) -> str:  # pragma: no cover
        return self.name


class Post(models.Model):
    """A lost (``lost``) or found (``found``) post; both share one table (contract §3.5)."""

    POST_TYPES = [("lost", "失物"), ("found", "招领")]
    STATUSES = [
        ("open", "进行中"),
        ("in_handover", "交接中"),
        ("completed", "已完成"),
        ("withdrawn", "已撤回"),
    ]
    PUBLIC_STATUSES = ("open", "in_handover", "completed")

    id = models.CharField(primary_key=True, max_length=64)
    post_type = models.CharField(max_length=8, choices=POST_TYPES)
    title = models.CharField(max_length=60)
    description = models.TextField(blank=True, default="")
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="posts")
    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="posts")
    status = models.CharField(max_length=16, choices=STATUSES, default="open")
    occurred_at = models.DateTimeField()
    publisher = models.ForeignKey(
        "identity.DemoUser", on_delete=models.PROTECT, related_name="posts"
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "失物/招领信息"
        verbose_name_plural = "失物/招领信息"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["status", "post_type"], name="ix_posts_status_type"),
            models.Index(fields=["category", "status"], name="ix_posts_category_status"),
            models.Index(fields=["location", "status"], name="ix_posts_location_status"),
            models.Index(fields=["publisher", "-created_at"], name="ix_posts_publisher"),
        ]

    @property
    def campus_id(self) -> str:
        """Campus is derived from the dictionary location (contract §3.4)."""
        return self.location.campus_id

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.post_type}:{self.title}"
