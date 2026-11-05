"""Idempotent replay for write endpoints.

Same user + same operation + same client key + same request hash replays the first response.
A changed body under the same key is a conflict (409), never a silent second execution.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import IdempotencyRecord
from app.repos import idempotency_repo


@dataclass(frozen=True)
class Replay:
    status_code: int
    body: dict


def _request_hash(operation: str, payload: dict) -> str:
    canonical = json.dumps({"operation": operation, "payload": payload}, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def check(
    session: Session,
    *,
    actor: str,
    operation: str,
    client_key: str | None,
    payload: dict,
) -> Replay | None:
    if not client_key:
        return None
    record = idempotency_repo.get(session, idempotency_repo.make_key(actor, operation, client_key))
    if record is None:
        return None
    if record.request_hash != _request_hash(operation, payload):
        raise AppError(409, "idempotency_conflict", "同一 Idempotency-Key 的请求内容不一致")
    return Replay(status_code=record.response_status, body=json.loads(record.response_body))


def remember(
    session: Session,
    *,
    actor: str,
    operation: str,
    client_key: str | None,
    payload: dict,
    status_code: int,
    body: dict,
    now,
) -> None:
    if not client_key:
        return
    idempotency_repo.add(
        session,
        IdempotencyRecord(
            idem_key=idempotency_repo.make_key(actor, operation, client_key),
            user_id=actor,
            operation=operation,
            request_hash=_request_hash(operation, payload),
            response_status=status_code,
            response_body=json.dumps(body, ensure_ascii=False, default=str),
            created_at=now,
        ),
    )
