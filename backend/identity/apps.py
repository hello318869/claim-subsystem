from __future__ import annotations

from django.apps import AppConfig


class IdentityConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "identity"
    verbose_name = "演示身份（A 模块适配器）"
