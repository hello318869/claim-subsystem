from __future__ import annotations

import pytest

from app.errors import AppError
from app.state_machine import can_transition, ensure_transition, is_terminal


def test_allowed_paths():
    assert can_transition("PENDING", "APPROVED")
    assert can_transition("PENDING", "REJECTED")
    assert can_transition("PENDING", "WITHDRAWN")
    assert can_transition("PENDING", "CLOSED_OTHER")
    assert can_transition("APPROVED", "COMPLETED")
    assert can_transition("APPROVED", "DISPUTED")
    assert can_transition("APPROVED", "EXPIRED")


def test_terminal_states_never_leave():
    for status in ("REJECTED", "WITHDRAWN", "CLOSED_OTHER", "EXPIRED", "DISPUTED", "COMPLETED"):
        assert is_terminal(status)
        for target in ("PENDING", "APPROVED", "COMPLETED", "REJECTED"):
            assert not can_transition(status, target)


def test_illegal_transition_raises_409():
    with pytest.raises(AppError) as exc:
        ensure_transition("COMPLETED", "APPROVED")
    assert exc.value.status_code == 409
    assert exc.value.code == "invalid_transition"


def test_unknown_status_is_rejected():
    assert not can_transition("WHATEVER", "APPROVED")
