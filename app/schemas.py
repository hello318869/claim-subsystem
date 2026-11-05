"""Request bodies and query parameters.

Whitespace-only values are rejected after stripping; ``min_length`` alone would let
``"   "`` through and store an empty evidence text or message body.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


def _required_text(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError("不能只包含空白字符")
    return stripped


class DemoTokenRequest(BaseModel):
    actor: str = Field(min_length=1, max_length=32)


class ClaimCreateRequest(BaseModel):
    item_id: str = Field(max_length=64)
    evidence_text: str = Field(max_length=2000)
    item_number: str | None = Field(default=None, max_length=64)

    @field_validator("item_id", "evidence_text")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        return _required_text(value)

    @field_validator("item_number")
    @classmethod
    def _optional_number(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class ReasonRequest(BaseModel):
    reason: str = Field(max_length=500)

    @field_validator("reason")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        return _required_text(value)


class MessageRequest(BaseModel):
    text: str = Field(max_length=2000)

    @field_validator("text")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        return _required_text(value)


class HandoverConfirmRequest(BaseModel):
    code: str = Field(min_length=4, max_length=32)

    @field_validator("code")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        return _required_text(value)


class ResetRequest(BaseModel):
    reason: str = Field(default="", max_length=500)

    @field_validator("reason")
    @classmethod
    def _optional_reason(cls, value: str) -> str:
        return value.strip()
