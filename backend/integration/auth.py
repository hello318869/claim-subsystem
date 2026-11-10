"""B reads the shared in-process identity resolved by DRF's Bearer adapter."""

from common.contracts import UserSummary
from common.errors import AppError


def current_actor(request) -> UserSummary | None:
    return request.user


def require_actor(request) -> UserSummary:
    actor = current_actor(request)
    if actor is None:
        raise AppError(401, "UNAUTHENTICATED", "请先登录", headers={"WWW-Authenticate": "Bearer"})
    return actor


def require_campus_verified(actor: UserSummary) -> None:
    if not actor.is_campus_verified:
        raise AppError(403, "IDENTITY_REQUIRED", "发布招领信息需要先完成校园身份绑定")
