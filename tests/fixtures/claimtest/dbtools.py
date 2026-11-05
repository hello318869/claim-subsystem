"""Narrow, claim_test-only SQL seams for time-sensitive tests.

No general SQL execution is exposed: every statement is fixed and parameterised.
The connection is opened through :func:`claimtest.env.connect_test_db`, which
asserts ``DATABASE() == 'claim_test'`` before use.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Mapping

from .env import TestEnv, connect_test_db


class TestDatabase:
    def __init__(self, env: TestEnv) -> None:
        self._env = env

    def _execute(self, sql: str, params: Mapping[str, Any] | None = None) -> None:
        conn = connect_test_db(self._env)
        try:
            with conn.cursor() as cursor:
                cursor.execute(sql, dict(params or {}))
            conn.commit()
        finally:
            conn.close()

    def _fetchone(self, sql: str, params: Mapping[str, Any]) -> tuple | None:
        conn = connect_test_db(self._env)
        try:
            with conn.cursor() as cursor:
                cursor.execute(sql, dict(params))
                return cursor.fetchone()
        finally:
            conn.close()

    def _fetchall(self, sql: str, params: Mapping[str, Any]) -> list[tuple]:
        conn = connect_test_db(self._env)
        try:
            with conn.cursor() as cursor:
                cursor.execute(sql, dict(params))
                return list(cursor.fetchall())
        finally:
            conn.close()

    def expire_code(self, claim_id: str) -> None:
        """Move the current handover code expiry into the past (code -> 410)."""

        self._execute(
            "UPDATE handover_codes "
            "SET expires_at = UTC_TIMESTAMP() - INTERVAL 1 SECOND "
            "WHERE claim_id = %(claim_id)s",
            {"claim_id": claim_id},
        )

    def expire_handover_deadline(self, claim_id: str) -> None:
        """Move the claim's absolute 24h handover deadline into the past."""

        self._execute(
            "UPDATE claims "
            "SET handover_deadline = UTC_TIMESTAMP() - INTERVAL 1 HOUR "
            "WHERE id = %(claim_id)s",
            {"claim_id": claim_id},
        )

    def end_cooldown(self, claim_id: str, role: str = "applicant") -> None:
        if role not in {"applicant", "finder"}:
            raise ValueError("role must be applicant or finder")
        self._execute(
            f"UPDATE handover_codes "
            f"SET cooldown_until_{role} = UTC_TIMESTAMP() - INTERVAL 1 SECOND "
            f"WHERE claim_id = %(claim_id)s",
            {"claim_id": claim_id},
        )

    def get_code_row(self, claim_id: str) -> Mapping[str, Any] | None:
        row = self._fetchone(
            "SELECT nonce, expires_at, reset_count, attempts_applicant, "
            "attempts_finder, cooldown_until_applicant, cooldown_until_finder, "
            "cooldown_triggered_applicant, cooldown_triggered_finder "
            "FROM handover_codes WHERE claim_id = %(claim_id)s",
            {"claim_id": claim_id},
        )
        if row is None:
            return None
        keys = (
            "nonce",
            "expires_at",
            "reset_count",
            "attempts_applicant",
            "attempts_finder",
            "cooldown_until_applicant",
            "cooldown_until_finder",
            "cooldown_triggered_applicant",
            "cooldown_triggered_finder",
        )
        return dict(zip(keys, row))

    def get_claim_row(self, claim_id: str) -> Mapping[str, Any] | None:
        row = self._fetchone(
            "SELECT status, handover_deadline, approved_at "
            "FROM claims WHERE id = %(claim_id)s",
            {"claim_id": claim_id},
        )
        if row is None:
            return None
        return dict(zip(("status", "handover_deadline", "approved_at"), row))

    def count_claims_for_item(self, item_id: str) -> int:
        row = self._fetchone(
            "SELECT COUNT(*) FROM claims WHERE item_id = %(item_id)s",
            {"item_id": item_id},
        )
        return int(row[0]) if row else 0

    def count_pending_claims(self, item_id: str, applicant_id: str) -> int:
        row = self._fetchone(
            "SELECT COUNT(*) FROM claims "
            "WHERE item_id = %(item_id)s AND applicant_id = %(applicant_id)s "
            "AND status = 'PENDING'",
            {"item_id": item_id, "applicant_id": applicant_id},
        )
        return int(row[0]) if row else 0

    def count_approvals(self, item_id: str) -> int:
        row = self._fetchone(
            "SELECT COUNT(*) FROM item_approvals WHERE item_id = %(item_id)s",
            {"item_id": item_id},
        )
        return int(row[0]) if row else 0

    def get_claim_status(self, claim_id: str) -> str | None:
        row = self._fetchone(
            "SELECT status FROM claims WHERE id = %(claim_id)s",
            {"claim_id": claim_id},
        )
        return str(row[0]) if row else None

    def get_claim_reason(self, claim_id: str) -> str | None:
        row = self._fetchone(
            "SELECT reason FROM claims WHERE id = %(claim_id)s",
            {"claim_id": claim_id},
        )
        return None if row is None or row[0] is None else str(row[0])

    def set_listing_status(self, item_id: str, status: str) -> None:
        allowed = {"published", "claimed", "withdrawn", "archived", "removed"}
        if status not in allowed:
            raise ValueError(f"unexpected listing status {status!r}")
        self._execute(
            "UPDATE listing_snapshots SET status = %(status)s "
            "WHERE item_id = %(item_id)s",
            {"status": status, "item_id": item_id},
        )

    def message_ids(self, claim_id: str) -> list[str]:
        rows = self._fetchall(
            "SELECT id FROM messages WHERE claim_id = %(claim_id)s",
            {"claim_id": claim_id},
        )
        return [str(row[0]) for row in rows]

    def count_messages(self, claim_id: str) -> int:
        return len(self.message_ids(claim_id))

    def insert_messages(
        self, claim_id: str, count: int, *, created_at: datetime | None = None
    ) -> list[str]:
        """Insert same-second messages for cursor regression tests.

        This bypasses the chat rate limit intentionally; message pages are the
        subject under test, not the write rate limiter.
        """

        if count <= 0:
            raise ValueError("count must be positive")
        moment = created_at or datetime.now(timezone.utc).replace(
            microsecond=0, tzinfo=None
        )
        if moment.tzinfo is not None:
            moment = moment.astimezone(timezone.utc).replace(tzinfo=None)
        ids = [str(uuid.uuid4()) for _ in range(count)]
        rows = [
            (
                message_id,
                claim_id,
                "applicant" if index % 2 == 0 else "finder",
                f"同秒分页回归消息 {index:03d}",
                moment,
            )
            for index, message_id in enumerate(ids)
        ]
        conn = connect_test_db(self._env)
        try:
            with conn.cursor() as cursor:
                cursor.executemany(
                    "INSERT INTO messages (id, claim_id, sender_role, body, created_at) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    rows,
                )
            conn.commit()
        finally:
            conn.close()
        return ids
