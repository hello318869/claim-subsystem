"""SQLAlchemy models.

Two rules encoded here:
* ``listing_snapshots`` mirrors external data read-only; only ``synced_at`` is local bookkeeping.
* A record can have at most one approved claim: ``item_approvals.item_id`` is the primary key,
  so the database itself refuses a second approval for the same item.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ListingSnapshot(Base):
    __tablename__ = "listing_snapshots"

    item_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    location: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="published")
    publisher_user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    origin: Mapped[str] = mapped_column(String(16), nullable=False, default="demo")
    synced_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        Index("ix_listing_kind_status", "kind", "status"),
        Index("ix_listing_publisher", "publisher_user_id"),
    )


class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    item_id: Mapped[str] = mapped_column(String(64), nullable=False)
    applicant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    finder_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING")
    evidence_text: Mapped[str] = mapped_column(Text, nullable=False)
    item_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    handover_deadline: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_claims_item_status", "item_id", "status"),
        Index("ix_claims_applicant", "applicant_id", "created_at"),
        Index("ix_claims_finder", "finder_id", "created_at"),
    )


class ItemApproval(Base):
    __tablename__ = "item_approvals"

    item_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    claim_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    approved_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    claim_id: Mapped[str] = mapped_column(String(36), nullable=False)
    sender_role: Mapped[str] = mapped_column(String(16), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (Index("ix_messages_claim_created", "claim_id", "created_at"),)


class HandoverCode(Base):
    __tablename__ = "handover_codes"

    claim_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    nonce: Mapped[str] = mapped_column(String(64), nullable=False)
    digest_applicant: Mapped[str] = mapped_column(String(64), nullable=False)
    digest_finder: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    attempts_applicant: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attempts_finder: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cooldown_until_applicant: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cooldown_until_finder: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cooldown_triggered_applicant: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cooldown_triggered_finder: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    confirmed_applicant: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    confirmed_finder: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reset_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    issued_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"

    idem_key: Mapped[str] = mapped_column(String(255), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (Index("ix_idem_created", "created_at"),)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    claim_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    item_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (Index("ix_audit_claim", "claim_id", "created_at"),)
