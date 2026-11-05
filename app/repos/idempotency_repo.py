"""Idempotency-key store.

Only sanitised response bodies are kept: no identity mapping, no plaintext handover code.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import IdempotencyRecord


def make_key(user_id: str, operation: str, client_key: str) -> str:
    return f"{user_id}:{operation}:{client_key}"[:255]


def get(session: Session, key: str) -> IdempotencyRecord | None:
    return session.get(IdempotencyRecord, key)


def add(session: Session, record: IdempotencyRecord) -> IdempotencyRecord:
    session.add(record)
    session.flush()
    return record
