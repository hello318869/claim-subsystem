"""Demo identity endpoint. Disabled unless DEMO_MODE=true."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends

from app.config import Settings
from app.errors import AppError
from app.routers.deps import get_settings_dep
from app.schemas import DemoTokenRequest
from app.security import issue_token

router = APIRouter(tags=["demo"])

DEMO_ACTORS = ("alice", "bob", "finder", "outsider")


@router.post("/demo/token")
def demo_token(
    payload: DemoTokenRequest,
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> dict:
    if not settings.demo_mode:
        raise AppError(403, "demo_disabled", "演示身份入口未开启")
    if payload.actor not in DEMO_ACTORS:
        raise AppError(422, "validation_error", "未知的演示身份", field="actor")
    token, expires_epoch = issue_token(
        payload.actor, settings.auth_secret, ttl_minutes=settings.token_ttl_minutes
    )
    return {
        "token": token,
        "actor": payload.actor,
        "expires_at": datetime.fromtimestamp(expires_epoch, tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
    }
