"""Idempotent replay for write endpoints.

Design (v1.0.1):
* The key is **claimed inside the business transaction** with a placeholder row. A concurrent
  request with the same key blocks on the primary key, then reads the committed row and
  replays it, so a duplicate key can never surface as a 500.
* The request fingerprint is a domain-separated HMAC over actor + operation + canonical body,
  never a bare SHA-256: handover codes are 8 digits and would be trivially enumerable.
* Only sanitised response bodies are stored; no handover code is ever cached.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings
from app.errors import AppError
from app.models import IdempotencyRecord
from app.repos import idempotency_repo

FINGERPRINT_DOMAIN = "idem-v1"


@dataclass(frozen=True)
class Replay:
    status_code: int
    body: dict


def _canonical(operation: str, payload: dict) -> str:
    return json.dumps({"operation": operation, "payload": payload}, sort_keys=True, ensure_ascii=False, default=str)


def fingerprint(settings: Settings, actor: str, operation: str, payload: dict) -> str:
    message = f"{FINGERPRINT_DOMAIN}|{actor}|{operation}|{_canonical(operation, payload)}"
    return hmac.new(settings.auth_secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


def claim(
    session: Session,
    settings: Settings,
    *,
    actor: str,
    operation: str,
    client_key: str | None,
    payload: dict,
    now,
) -> Replay | None:
    """Reserve the key or return the previous response.

    Must be called inside the same transaction as the business write: the placeholder row is
    committed together with the business result, so a rollback releases the key.
    """
    if not client_key:
        return None

    idem_key = idempotency_repo.make_key(actor, operation, client_key)
    request_hash = fingerprint(settings, actor, operation, payload)

    try:
        with session.begin_nested():
            idempotency_repo.add(
                session,
                IdempotencyRecord(
                    idem_key=idem_key,
                    user_id=actor,
                    operation=operation,
                    request_hash=request_hash,
                    response_status=0,
                    response_body="",
                    created_at=now,
                ),
            )
    except IntegrityError:
        # Somebody else holds (or held) this key. A locking read bypasses the REPEATABLE READ
        # snapshot, so the committed row is visible even when this transaction started earlier.
        row = session.execute(
            select(IdempotencyRecord).where(IdempotencyRecord.idem_key == idem_key).with_for_update()
        ).scalar_one_or_none()
        if row is None or row.request_hash != request_hash:
            raise AppError(409, "idempotency_conflict", "同一 Idempotency-Key 的请求内容不一致")
        if row.response_status == 0:
            raise AppError(409, "idempotency_conflict", "同一 Idempotency-Key 的请求仍在处理中")
        return Replay(status_code=row.response_status, body=json.loads(row.response_body))

    return None


def complete(
    session: Session,
    *,
    actor: str,
    operation: str,
    client_key: str | None,
    status_code: int,
    body: dict,
) -> None:
    if not client_key:
        return
    idem_key = idempotency_repo.make_key(actor, operation, client_key)
    session.execute(
        update(IdempotencyRecord)
        .where(IdempotencyRecord.idem_key == idem_key)
        .values(response_status=status_code, response_body=json.dumps(body, ensure_ascii=False, default=str))
    )
