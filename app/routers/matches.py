"""Rule-based matching endpoint (recommendations only)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.config import Settings
from app.routers.deps import current_actor, get_db, get_settings_dep
from app.services import match_service

router = APIRouter(tags=["matches"])


@router.get("/matches")
def get_matches(
    item_id: Annotated[str, Query(min_length=1)],
    actor: Annotated[str, Depends(current_actor)],
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> dict:
    return match_service.match_for_lost_item(session, settings, actor, item_id)
