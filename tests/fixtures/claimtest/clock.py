"""Out-of-process time control for expiry/cooldown tests.

There is no agreed application clock hook yet.  Sleeping for 60 seconds is
forbidden, so this module supports an explicit, test-only SQL seam configured by
the seed manifest.  The backend owner supplies exact UPDATE statements against
``claim_test`` once the table names are known; tests never guess a schema.

Accepted manifest shape::

    "clock": {
      "expire_code_sql":
        "UPDATE handover_codes SET expires_at = UTC_TIMESTAMP() - INTERVAL 1 SECOND "
        "WHERE claim_id = %(claim_id)s",
      "advance_claim_sql": [
        "UPDATE claim_handover SET cooldown_until = "
        "cooldown_until - INTERVAL %(seconds)s SECOND WHERE claim_id = %(claim_id)s"
      ]
    }

Every statement is executed on a connection whose current database has been
verified as ``claim_test``.  Only UPDATE statements with the two named bind
parameters are accepted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from .env import TestEnv, connect_test_db


class ClockUnavailable(RuntimeError):
    """No safe time seam has been configured."""


_ALLOWED_PLACEHOLDERS = {"claim_id", "seconds"}
_PLACEHOLDER_RE = re.compile(r"%\(([a-zA-Z_][a-zA-Z0-9_]*)\)s")


def _validate_statement(sql: str) -> str:
    statement = sql.strip().rstrip(";")
    if not statement:
        raise ClockUnavailable("empty clock SQL statement")
    if ";" in statement:
        raise ClockUnavailable("clock SQL must be a single statement")
    if not statement.lower().startswith("update "):
        raise ClockUnavailable("clock SQL must be a single UPDATE statement")
    lowered = statement.lower()
    if "claim_dev" in lowered or "information_schema" in lowered or "mysql." in lowered:
        raise ClockUnavailable("clock SQL must only touch the claim_test schema")
    placeholders = set(_PLACEHOLDER_RE.findall(statement))
    unknown = placeholders - _ALLOWED_PLACEHOLDERS
    if unknown:
        raise ClockUnavailable(
            f"clock SQL uses unsupported bind parameters: {', '.join(sorted(unknown))}"
        )
    return statement


@dataclass
class ClockSeam:
    config: Mapping[str, Any]
    env: TestEnv

    def __post_init__(self) -> None:
        self._expire_sql: str | None = (
            _validate_statement(str(self.config["expire_code_sql"]))
            if self.config.get("expire_code_sql")
            else None
        )
        advance = self.config.get("advance_claim_sql") or []
        if isinstance(advance, str):
            advance = [advance]
        if not isinstance(advance, list):
            raise ClockUnavailable("clock.advance_claim_sql must be a string or array")
        self._advance_sql: list[str] = [
            _validate_statement(str(item)) for item in advance
        ]

    @property
    def can_expire_code(self) -> bool:
        return self._expire_sql is not None

    @property
    def can_advance_claim(self) -> bool:
        return bool(self._advance_sql)

    def require_code_expiry(self) -> None:
        if not self.can_expire_code:
            raise ClockUnavailable(
                "no clock.expire_code_sql configured; add a claim_test-only UPDATE "
                "statement to the seed manifest to test code expiry without sleeping"
            )

    def require_advance(self) -> None:
        if not self.can_advance_claim:
            raise ClockUnavailable(
                "no clock.advance_claim_sql configured; cooldown recovery cannot be tested"
            )

    def _execute(self, statements: list[str], params: Mapping[str, Any]) -> None:
        conn = connect_test_db(self.env)
        try:
            with conn.cursor() as cursor:
                for statement in statements:
                    cursor.execute(statement, dict(params))
            conn.commit()
        finally:
            conn.close()

    def expire_code(self, claim_id: object) -> None:
        self.require_code_expiry()
        assert self._expire_sql is not None
        self._execute([self._expire_sql], {"claim_id": claim_id})

    def advance_for_claim(self, claim_id: object, seconds: int) -> None:
        self.require_advance()
        if seconds <= 0:
            raise ValueError("seconds must be positive")
        self._execute(self._advance_sql, {"claim_id": claim_id, "seconds": int(seconds)})
