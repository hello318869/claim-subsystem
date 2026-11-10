from __future__ import annotations

from django.apps import AppConfig


class PostsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "posts"
    verbose_name = "失物/招领信息（B 模块适配器）"
