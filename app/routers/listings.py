"""Read-only listing endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import serializers
from app.errors import AppError
from app.repos import listing_repo
from app.routers.deps import current_actor, get_db

router = APIRouter(tags=["listings"])


@router.get("/listings")
def list_listings(
    actor: Annotated[str, Depends(current_actor)],
    session: Annotated[Session, Depends(get_db)],
    kind: Annotated[str | None, Query(pattern="^(lost|found)$")] = None,
    mine: bool = False,
    q: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict:
    rows, total = listing_repo.list_page(
        session,
        kind=kind,
        publisher_user_id=actor if mine else None,
        query=q,
        page=page,
        page_size=page_size,
    )
    approved = listing_repo.approved_claim_ids(session, [row.item_id for row in rows])
    items = [serializers.public_listing(row, approved=row.item_id in approved) for row in rows]
    return serializers.page_dto(items, total, page, page_size)


@router.get("/listings/{item_id}")
def get_listing(
    item_id: str,
    actor: Annotated[str, Depends(current_actor)],
    session: Annotated[Session, Depends(get_db)],
) -> dict:
    row = listing_repo.get(session, item_id)
    if row is None:
        raise AppError(404, "not_found", "记录不存在")
    approved = listing_repo.approved_claim_id(session, item_id)
    return serializers.public_listing(row, approved=approved is not None)
