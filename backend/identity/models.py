"""Demo users and server-side sessions.

This app is a local stand-in for member A's subsystem: real accounts, campus binding and
``/auth/*`` endpoints are not implemented here.  What C needs from A is exactly the contract's
``UserSummary`` plus a revocable session token (contract §2.2), so the demo adapter stores only
that: fixed demo users and a digest of each issued token.  Swapping in A's real module means
replacing ``identity.services`` without touching the claim code.
"""

from __future__ import annotations

from django.db import models
from django.utils import timezone


class DemoUser(models.Model):
    """Contract ``UserSelf``/``UserSummary`` fields needed by the claim subsystem."""

    id = models.CharField(primary_key=True, max_length=64)
    username = models.CharField(max_length=32, unique=True)
    nickname = models.CharField(max_length=30)
    bio = models.CharField(max_length=200, blank=True, default="")
    is_campus_verified = models.BooleanField(default=False)
    verification_mode = models.CharField(max_length=16, null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "演示用户"
        verbose_name_plural = "演示用户"

    def __str__(self) -> str:  # pragma: no cover - admin/debug only
        return f"{self.username} ({self.id})"


class AuthToken(models.Model):
    """A revocable session; only the SHA-256 digest of the bearer token is stored."""

    token_hash = models.CharField(primary_key=True, max_length=64)
    user = models.ForeignKey(DemoUser, on_delete=models.CASCADE, related_name="tokens")
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "登录会话"
        verbose_name_plural = "登录会话"
        indexes = [models.Index(fields=["user", "expires_at"], name="ix_auth_token_user_exp")]

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None and self.expires_at > timezone.now()
