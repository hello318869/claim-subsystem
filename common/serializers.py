"""Strict request parsing helpers.

The contract (§2.1) requires ``400 VALIDATION_ERROR`` for unknown or read-only fields, while
DRF serializers silently ignore them.  :class:`StrictSerializer` closes that gap; the helpers
turn DRF's error detail into the contract envelope by raising ``ValidationError``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from rest_framework import exceptions, serializers

from common.errors import AppError


class StrictSerializer(serializers.Serializer):
    """Reject unknown keys and read-only fields instead of ignoring them."""

    def to_internal_value(self, data):
        if not isinstance(data, Mapping):
            raise serializers.ValidationError({"non_field_errors": ["请求体必须是 JSON 对象"]})
        errors: dict[str, list[str]] = {}
        for name, field in self.fields.items():
            if field.read_only and name in data:
                errors[name] = ["该字段只读，不能提交"]
        for name in data:
            if name not in self.fields:
                errors[str(name)] = ["不支持的字段"]
        if errors:
            raise serializers.ValidationError(errors)
        return super().to_internal_value(data)


class PageQuery(StrictSerializer):
    page = serializers.IntegerField(min_value=1, required=False, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=100, required=False, default=20)


def parse_body(serializer_class, request, *, optional: bool = False) -> dict[str, Any]:
    """Validate ``request.data`` as a JSON object and return the cleaned values."""
    try:
        data = request.data
    except exceptions.ParseError:
        if not optional:
            raise
        data = {}
    if data is None or data == "":
        data = {}
    if not isinstance(data, dict):
        raise AppError(400, "VALIDATION_ERROR", "请求体必须是 JSON 对象")
    serializer = serializer_class(data=data)
    serializer.is_valid(raise_exception=True)
    return dict(serializer.validated_data)


def parse_query(serializer_class, request) -> dict[str, Any]:
    """Validate known query parameters; unrelated parameters are ignored."""
    serializer = serializer_class(data=request.query_params)
    serializer.is_valid(raise_exception=True)
    return dict(serializer.validated_data)


def clean_text(value: Any, field: str, minimum: int, maximum: int) -> str:
    """Trim ordinary text and enforce the contract's character range."""
    if not isinstance(value, str):
        raise AppError(400, "VALIDATION_ERROR", "请输入文本", field=field)
    value = value.strip()
    if not minimum <= len(value) <= maximum:
        raise AppError(
            400, "VALIDATION_ERROR", f"文本长度应为 {minimum}～{maximum} 字", field=field
        )
    return value


def validate_resource_id(value: str, field: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 64:
        raise AppError(400, "VALIDATION_ERROR", "ID 格式不正确", field=field)
    return value
