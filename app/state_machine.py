"""Claim status machine as a pure, directly testable table.

Terminal states never leave themselves. Any other transition raises 409; callers must not
"absorb" an illegal event as success.
"""

from __future__ import annotations

from enum import StrEnum

from app.errors import AppError


class Status(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    CLOSED_OTHER = "CLOSED_OTHER"
    EXPIRED = "EXPIRED"
    DISPUTED = "DISPUTED"
    COMPLETED = "COMPLETED"


PENDING = Status.PENDING
APPROVED = Status.APPROVED
REJECTED = Status.REJECTED
WITHDRAWN = Status.WITHDRAWN
CLOSED_OTHER = Status.CLOSED_OTHER
EXPIRED = Status.EXPIRED
DISPUTED = Status.DISPUTED
COMPLETED = Status.COMPLETED

ALLOWED: dict[Status, frozenset[Status]] = {
    PENDING: frozenset({APPROVED, REJECTED, WITHDRAWN, CLOSED_OTHER, EXPIRED}),
    APPROVED: frozenset({COMPLETED, DISPUTED, EXPIRED}),
    REJECTED: frozenset(),
    WITHDRAWN: frozenset(),
    CLOSED_OTHER: frozenset(),
    EXPIRED: frozenset(),
    DISPUTED: frozenset(),
    COMPLETED: frozenset(),
}

TERMINAL = frozenset({REJECTED, WITHDRAWN, CLOSED_OTHER, EXPIRED, DISPUTED, COMPLETED})


def can_transition(current: str, target: str) -> bool:
    try:
        source = Status(current)
        destination = Status(target)
    except ValueError:
        return False
    return destination in ALLOWED[source]


def ensure_transition(current: str, target: str) -> Status:
    if not can_transition(current, target):
        raise AppError(409, "invalid_transition", f"状态 {current} 不允许迁移到 {target}")
    return Status(target)


def is_terminal(status: str) -> bool:
    try:
        return Status(status) in TERMINAL
    except ValueError:
        return True
