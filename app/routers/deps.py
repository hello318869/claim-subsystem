"""FastAPI dependencies: settings, session, identity port, current actor."""

from __future__ import annotations

from typing import Annotated, Iterator

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.errors import AppError
from app.ports import IdentityPort
from app.security import verify_token


class TokenIdentity:
    """Demo/real identity adapter: verify signature and expiry, return the opaque subject."""

    def __init__(self, secret: str) -> None:
        self._secret = secret

    def resolve(self, token: str) -> str:
        return verify_token(token, self._secret)["sub"]


def get_settings_dep() -> Settings:
    return get_settings()


def get_identity(settings: Annotated[Settings, Depends(get_settings_dep)]) -> IdentityPort:
    return TokenIdentity(settings.auth_secret)


def get_db() -> Iterator[Session]:
    yield from get_session()


def current_actor(
    identity: Annotated[IdentityPort, Depends(get_identity)],
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AppError(401, "unauthorized", "缺少 Bearer 令牌")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise AppError(401, "unauthorized", "缺少 Bearer 令牌")
    return identity.resolve(token)
