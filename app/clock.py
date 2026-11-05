"""UTC clock helpers.

Database columns store naive UTC; every boundary serialises back to ISO-8601 with `Z`.
"""

from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_db(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def from_db(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    moment = from_db(value)
    assert moment is not None
    return moment.isoformat().replace("+00:00", "Z")
