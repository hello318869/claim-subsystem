"""UTC time helpers.

Database values are timezone-aware UTC (``USE_TZ = True``); every boundary renders ISO-8601
with a trailing ``Z`` as required by contract §2.1.
"""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso(value: datetime | None) -> str | None:
    """Render an aware/naive datetime as ISO-8601 UTC (``2026-10-07T02:00:00Z``)."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
