"""B dictionaries, lost/found posts and privately stored images."""

from __future__ import annotations

import os
import uuid

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.db import models
from django.utils import timezone


def new_post_id() -> str:
    return str(uuid.uuid4())


class PrivateImageStorage(FileSystemStorage):
    """Image contents are served only by B's permission-checked endpoint."""

    @property
    def base_location(self):
        return settings.PRIVATE_MEDIA_ROOT

    @property
    def location(self):
        return os.path.abspath(str(self.base_location))


private_image_storage = PrivateImageStorage()


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

    POST_TYPE_LOST = "lost"
    POST_TYPE_FOUND = "found"
    STATUS_OPEN = "open"
    STATUS_IN_HANDOVER = "in_handover"
    STATUS_COMPLETED = "completed"
    STATUS_WITHDRAWN = "withdrawn"
    POST_TYPES = [(POST_TYPE_LOST, "失物"), (POST_TYPE_FOUND, "招领")]
    STATUSES = [
        ("open", "进行中"),
        ("in_handover", "交接中"),
        ("completed", "已完成"),
        ("withdrawn", "已撤回"),
    ]
    #: 公开列表默认展示的状态（契约 3.5：open 与 in_handover；completed 需显式筛选）
    #: 权威定义在 posts.constants.PUBLIC_STATUSES，这里同步一份供模型层引用。
    PUBLIC_STATUSES = ("open", "in_handover")

    id = models.CharField(primary_key=True, max_length=64, default=new_post_id)
    post_type = models.CharField(max_length=8, choices=POST_TYPES)
    title = models.CharField(max_length=60)
    description = models.TextField()
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="posts")
    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="posts")
    location_detail = models.CharField(max_length=100, blank=True, default="")
    handover_note = models.CharField(max_length=200, null=True, blank=True)
    request_id = models.CharField(max_length=64, null=True, blank=True)
    status = models.CharField(max_length=16, choices=STATUSES, default="open")
    occurred_at = models.DateTimeField()
    publisher_id = models.CharField(max_length=64, db_column="publisher_id", db_index=True)
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
            models.Index(fields=["publisher_id", "-created_at"], name="ix_posts_publisher"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["publisher_id", "request_id"], name="uniq_post_publisher_request"),
        ]

    def save(self, *args, **kwargs):
        """任何保存都刷新 ``updated_at``（契约 3.9 要求它反映最近一次修改）。"""
        self.updated_at = timezone.now()
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | {"updated_at"}
        super().save(*args, **kwargs)

    @property
    def campus_id(self) -> str:
        """Campus is derived from the dictionary location (contract §3.4)."""
        return self.location.campus_id

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.post_type}:{self.title}"


class PostImage(models.Model):
    owner_id = models.CharField(max_length=64, db_index=True)
    post = models.ForeignKey(Post, null=True, blank=True, on_delete=models.SET_NULL, related_name="images")
    file = models.FileField(storage=private_image_storage, upload_to="post-images/", max_length=255)
    mime_type = models.CharField(max_length=32)
    size_bytes = models.PositiveIntegerField()
    sort_order = models.PositiveIntegerField(default=0)
    alt_text = models.CharField(max_length=100)
    is_public = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sort_order", "id"]

    def save_bytes(self, data: bytes, mime_type: str) -> None:
        extension = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[mime_type]
        self.file.save(f"{uuid.uuid4().hex}.{extension}", ContentFile(data), save=False)
        self.mime_type = mime_type
        self.size_bytes = len(data)

    def delete_file(self) -> None:
        """删除私有存储里的文件；文件字段为空或文件已丢失时不抛异常。

        ``cleanup_images`` 会批量清理未绑定图片，历史数据里可能已经有 file 为空的记录，
        缺少这层保护会让整条清理命令在中途中断（后续图片都删不掉）。
        """
        if not self.file:
            return
        try:
            self.file.delete(save=False)
        except FileNotFoundError:
            return
