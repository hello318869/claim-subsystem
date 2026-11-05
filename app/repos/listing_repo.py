"""Read-only snapshot repository for external listing data."""

from __future__ import annotations

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.models import ItemApproval, ListingSnapshot


def get(session: Session, item_id: str) -> ListingSnapshot | None:
    return session.get(ListingSnapshot, item_id)


def lock(session: Session, item_id: str) -> ListingSnapshot | None:
    """Lock the item row first. Every state-changing transaction starts here.

    ``populate_existing`` refreshes any already-loaded instance after the lock wait.
    """

    statement = (
        select(ListingSnapshot)
        .where(ListingSnapshot.item_id == item_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return session.execute(statement).scalar_one_or_none()


def _filters(
    statement: Select,
    *,
    kind: str | None,
    publisher_user_id: str | None,
    query: str | None,
) -> Select:
    if kind:
        statement = statement.where(ListingSnapshot.kind == kind)
    if publisher_user_id:
        statement = statement.where(ListingSnapshot.publisher_user_id == publisher_user_id)
    if query:
        like = f"%{query.strip()}%"
        statement = statement.where(
            or_(
                ListingSnapshot.title.like(like),
                ListingSnapshot.description.like(like),
                ListingSnapshot.location.like(like),
                ListingSnapshot.category.like(like),
            )
        )
    return statement


def list_page(
    session: Session,
    *,
    kind: str | None,
    publisher_user_id: str | None,
    query: str | None,
    page: int,
    page_size: int,
) -> tuple[list[ListingSnapshot], int]:
    base = _filters(
        select(ListingSnapshot),
        kind=kind,
        publisher_user_id=publisher_user_id,
        query=query,
    )
    total = session.execute(
        _filters(
            select(func.count()).select_from(ListingSnapshot),
            kind=kind,
            publisher_user_id=publisher_user_id,
            query=query,
        )
    ).scalar_one()
    rows = (
        session.execute(
            base.order_by(ListingSnapshot.occurred_at.desc(), ListingSnapshot.item_id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )
    return list(rows), int(total)


def approved_claim_id(session: Session, item_id: str, *, for_update: bool = False) -> str | None:
    if for_update:
        approval = session.execute(
            select(ItemApproval)
            .where(ItemApproval.item_id == item_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
    else:
        approval = session.get(ItemApproval, item_id)
    return approval.claim_id if approval else None


def approved_claim_ids(session: Session, item_ids: list[str]) -> set[str]:
    if not item_ids:
        return set()
    rows = session.execute(
        select(ItemApproval.item_id).where(ItemApproval.item_id.in_(item_ids))
    ).scalars()
    return set(rows)


def lock_free_published_founds(session: Session, limit: int = 500) -> list[ListingSnapshot]:
    statement = (
        select(ListingSnapshot)
        .where(ListingSnapshot.kind == "found", ListingSnapshot.status == "published")
        .order_by(ListingSnapshot.occurred_at.desc())
        .limit(limit)
    )
    return list(session.execute(statement).scalars().all())
