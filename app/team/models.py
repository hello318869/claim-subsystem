"""Persistence for the shared A/B/C contract."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


_UTC_DATETIME = DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")


class Claim(Base):
    __tablename__ = "team_claims"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    post_id: Mapped[str] = mapped_column(String(64), nullable=False)
    applicant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    publisher_id: Mapped[str] = mapped_column(String(64), nullable=False)
    verification_text: Mapped[str] = mapped_column(String(1000), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    decision_note: Mapped[str | None] = mapped_column(String(500))
    close_reason: Mapped[str | None] = mapped_column(String(32))
    applicant_confirmed_at: Mapped[datetime | None] = mapped_column(_UTC_DATETIME)
    publisher_confirmed_at: Mapped[datetime | None] = mapped_column(_UTC_DATETIME)
    cancelled_by_id: Mapped[str | None] = mapped_column(String(64))
    completed_at: Mapped[datetime | None] = mapped_column(_UTC_DATETIME)
    created_at: Mapped[datetime] = mapped_column(_UTC_DATETIME, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(_UTC_DATETIME, nullable=False)

    __table_args__ = (
        Index("ix_team_claims_post_id", "post_id", "id"),
        Index("ix_team_claims_applicant_created", "applicant_id", "created_at", "id"),
        Index("ix_team_claims_publisher_created", "publisher_id", "created_at", "id"),
    )


class ClaimMessage(Base):
    __tablename__ = "team_claim_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    claim_id: Mapped[str] = mapped_column(ForeignKey("team_claims.id"), nullable=False)
    sender_id: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[str] = mapped_column(String(1000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(_UTC_DATETIME, nullable=False)

    __table_args__ = (Index("ix_team_claim_messages_claim_id", "claim_id", "id"),)
