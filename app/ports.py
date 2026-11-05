"""Ports for the two external read-only dependencies.

The services depend on these narrow protocols, not on HTTP details. The demo adapters are
local; swapping in the other members' services later touches only this module's adapters.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from sqlalchemy.orm import Session


class IdentityPort(Protocol):
    """Resolve a bearer token to an opaque user id, or raise 401."""

    def resolve(self, token: str) -> str: ...


class ListingSource(Protocol):
    """Read-only access to published lost/found records."""

    def get(self, session: Session, item_id: str) -> object | None: ...

    def list_page(
        self,
        session: Session,
        *,
        kind: str | None,
        publisher_user_id: str | None,
        query: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[object], int]: ...


class HandoverClock(Protocol):
    def now(self) -> datetime: ...
