"""Identity adapter used by C: issue, resolve and revoke demo sessions.

The functions mirror contract §7.3 (``require_user`` / ``get_user_summaries``).  They are the
only place that knows how a bearer token becomes a ``UserSummary``.
"""

from __future__ import annotations

from datetime import timedelta
from hashlib import sha256
from secrets import token_urlsafe

from django.conf import settings
from django.utils import timezone

from common.clock import iso
from common.contracts import UserSummary
from common.errors import AppError
from identity.models import AuthToken, DemoUser


def _digest(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def _summary(user: DemoUser) -> UserSummary:
    return UserSummary(
        id=user.id,
        nickname=user.nickname,
        is_campus_verified=user.is_campus_verified,
        verification_mode=user.verification_mode,
    )


def user_self(user: DemoUser) -> dict:
    """``UserSelf`` shape (contract §3.9), available for a future A module."""
    return {
        "id": user.id,
        "username": user.username,
        "nickname": user.nickname,
        "bio": user.bio,
        "is_campus_verified": user.is_campus_verified,
        "verification_mode": user.verification_mode,
        "created_at": iso(user.created_at),
        "updated_at": iso(user.updated_at),
    }


def issue_token(actor_id: str) -> dict:
    """Create an independent session for a demo actor (24h by default, contract §2.2)."""
    user = DemoUser.objects.filter(pk=actor_id).first()
    if user is None:
        raise AppError(400, "VALIDATION_ERROR", "未知的演示身份", field="actor")

    now = timezone.now()
    AuthToken.objects.filter(expires_at__lt=now).delete()
    token = token_urlsafe(32)
    expires_at = now + timedelta(hours=settings.DEMO_TOKEN_TTL_HOURS)
    AuthToken.objects.create(
        token_hash=_digest(token),
        user=user,
        created_at=now,
        expires_at=expires_at,
    )
    return {
        "access_token": token,
        "token_type": "Bearer",
        "expires_at": iso(expires_at),
        "user": user_self(user),
    }


def require_user(token: str) -> UserSummary:
    row = AuthToken.objects.select_related("user").filter(pk=_digest(token)).first()
    if row is None or not row.is_active:
        raise AppError(
            401,
            "UNAUTHENTICATED",
            "会话已过期或已退出",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _summary(row.user)


def logout(token: str) -> None:
    row = AuthToken.objects.filter(pk=_digest(token)).first()
    if row is None or not row.is_active:
        raise AppError(
            401,
            "UNAUTHENTICATED",
            "会话已过期或已退出",
            headers={"WWW-Authenticate": "Bearer"},
        )
    row.revoked_at = timezone.now()
    row.save(update_fields=["revoked_at"])


def get_user_summaries(user_ids: set[str]) -> dict[str, UserSummary]:
    if not user_ids:
        return {}
    return {
        user.id: _summary(user)
        for user in DemoUser.objects.filter(pk__in=user_ids)
    }
