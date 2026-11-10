"""Shared user summaries and a compatibility adapter for local demo sessions.

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
from common.contracts import UserSummary, deleted_user_summary
from common.errors import AppError
from identity.models import AuthToken, DemoUser
from users.authentication import resolve_session
from users.services import get_user_summaries as get_account_summaries


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
    session = resolve_session(token)
    if session is not None:
        return UserSummary(
            id=str(session.user_id),
            nickname=session.user.nickname,
            is_campus_verified=session.user.is_campus_verified,
            verification_mode=session.user.verification_mode or None,
        )
    row = AuthToken.objects.select_related("user").filter(pk=_digest(token)).first() if settings.DEMO_MODE else None
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
    # A's primary keys are integers, while the earlier demo uses IDs such as "alice".
    account_ids = {
        user_id for user_id in user_ids
        if user_id.isascii() and user_id.isdecimal() and len(user_id) <= 19
        and int(user_id) <= 9_223_372_036_854_775_807
    }
    accounts = {
        user_id: UserSummary(**record)
        for user_id, record in get_account_summaries(account_ids).items()
    } if account_ids else {}
    accounts.update({
        user.id: _summary(user)
        for user in DemoUser.objects.filter(pk__in=user_ids - accounts.keys())
    })
    # v0.5 §7.1：账号已注销、数据被清理或 A 暂时不可用时降级成占位摘要，
    # 不能因为个别用户缺失就让整页列表或详情失败。
    for user_id in user_ids - accounts.keys():
        accounts[user_id] = deleted_user_summary(user_id)
    return accounts
