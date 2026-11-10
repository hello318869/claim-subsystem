from __future__ import annotations

from django.apps import AppConfig


class ClaimsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "claims"
    verbose_name = "失物认领"
