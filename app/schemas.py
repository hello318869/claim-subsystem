"""Request bodies and query parameters."""

from __future__ import annotations

from pydantic import BaseModel, Field


class DemoTokenRequest(BaseModel):
    actor: str = Field(min_length=1, max_length=32)


class ClaimCreateRequest(BaseModel):
    item_id: str = Field(min_length=1, max_length=64)
    evidence_text: str = Field(min_length=1, max_length=2000)
    item_number: str | None = Field(default=None, max_length=64)


class ReasonRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class MessageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class HandoverConfirmRequest(BaseModel):
    code: str = Field(min_length=4, max_length=32)


class ResetRequest(BaseModel):
    reason: str = Field(default="", max_length=500)
