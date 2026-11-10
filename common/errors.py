"""Error envelope and DRF exception handler.

Every failure uses the body from contract §2.4::

    {"code": "...", "message": "...", "data": null, "errors": {...}}

Business failures are raised as :class:`AppError` (an ``APIException`` subclass) so they work
from views, authentication and services alike.  Unexpected defects become 500 ``INTERNAL_ERROR``
without leaking a stack trace, SQL or an internal path.
"""

from __future__ import annotations

import logging
from typing import Any

from django.http import Http404, JsonResponse
from rest_framework import exceptions
from rest_framework import status as http_status
from rest_framework.response import Response

logger = logging.getLogger("claims")

_METHOD_CODES = {
    400: "VALIDATION_ERROR",
    401: "UNAUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    413: "FILE_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    429: "RATE_LIMITED",
}


class AppError(exceptions.APIException):
    """Carries the contract ``code``, message, field errors and extra headers."""

    status_code = http_status.HTTP_500_INTERNAL_SERVER_ERROR
    default_detail = "服务器内部错误"
    default_code = "INTERNAL_ERROR"

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        field: str | None = None,
        errors: dict[str, list[str]] | None = None,
        headers: dict[str, str] | None = None,
        retry_after_seconds: int | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.field = field
        self.errors = dict(errors or {})
        if field and not self.errors:
            self.errors = {field: [message]}
        self.headers = dict(headers or {})
        self.retry_after_seconds = retry_after_seconds
        super().__init__(detail=message, code=code)


def error_payload(
    code: str,
    message: str,
    errors: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    return {"code": code, "message": message, "data": None, "errors": dict(errors or {})}


def error_response(
    status_code: int,
    code: str,
    message: str,
    errors: dict[str, list[str]] | None = None,
    *,
    headers: dict[str, str] | None = None,
    retry_after_seconds: int | None = None,
) -> Response:
    response = Response(error_payload(code, message, errors), status=status_code)
    for name, value in (headers or {}).items():
        response[name] = value
    if retry_after_seconds is not None:
        response.setdefault("Retry-After", str(retry_after_seconds))
    return response


def _messages(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    if isinstance(value, dict):
        return [f"{key}: {item}" for key, item in value.items()]
    return [str(value)]


def flatten_errors(detail: Any) -> dict[str, list[str]]:
    """Turn any DRF ``detail`` into the contract's ``{field: [messages]}`` object."""
    if isinstance(detail, dict):
        return {str(key): _messages(value) for key, value in detail.items()}
    if isinstance(detail, (list, tuple)):
        return {"non_field_errors": [str(item) for item in detail]}
    return {"non_field_errors": [str(detail)]}


def contract_exception_handler(exc, context) -> Response | None:
    """``EXCEPTION_HANDLER`` for DRF: always answers in the contract envelope."""
    if isinstance(exc, AppError):
        return error_response(
            exc.status_code,
            exc.code,
            exc.message,
            exc.errors,
            headers=exc.headers,
            retry_after_seconds=exc.retry_after_seconds,
        )

    if isinstance(exc, exceptions.ValidationError):
        return error_response(
            http_status.HTTP_400_BAD_REQUEST,
            "VALIDATION_ERROR",
            "请检查填写内容",
            flatten_errors(exc.detail),
        )

    if isinstance(exc, exceptions.NotAuthenticated):
        return error_response(
            http_status.HTTP_401_UNAUTHORIZED,
            "UNAUTHENTICATED",
            str(exc.detail) or "请先登录",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if isinstance(exc, exceptions.AuthenticationFailed):
        return error_response(
            http_status.HTTP_401_UNAUTHORIZED,
            "UNAUTHENTICATED",
            str(exc.detail) or "登录凭证无效",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if isinstance(exc, exceptions.PermissionDenied):
        return error_response(http_status.HTTP_403_FORBIDDEN, "FORBIDDEN", "没有操作权限")

    if isinstance(exc, (exceptions.NotFound, Http404)):
        return error_response(http_status.HTTP_404_NOT_FOUND, "NOT_FOUND", "请求的资源不存在")

    if isinstance(exc, exceptions.MethodNotAllowed):
        return error_response(http_status.HTTP_405_METHOD_NOT_ALLOWED, "METHOD_NOT_ALLOWED", "请求方法不允许")

    if isinstance(exc, exceptions.ParseError):
        return error_response(http_status.HTTP_400_BAD_REQUEST, "VALIDATION_ERROR", "请求体不是有效的 JSON")

    if isinstance(exc, exceptions.UnsupportedMediaType):
        return error_response(
            http_status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "UNSUPPORTED_MEDIA_TYPE",
            "请使用 application/json 提交数据",
        )

    if isinstance(exc, exceptions.Throttled):
        return error_response(
            http_status.HTTP_429_TOO_MANY_REQUESTS,
            "RATE_LIMITED",
            "请求过于频繁，请稍后再试",
            retry_after_seconds=int(exc.wait) if exc.wait is not None else None,
        )

    if isinstance(exc, exceptions.APIException):
        status_code = exc.status_code
        return error_response(
            status_code,
            _METHOD_CODES.get(status_code, "HTTP_ERROR"),
            str(exc.detail),
            headers=getattr(exc, "headers", None),
        )

    logger.exception("未处理的服务端异常")
    return error_response(
        http_status.HTTP_500_INTERNAL_SERVER_ERROR,
        "INTERNAL_ERROR",
        "服务器内部错误",
    )


def handler404(request, exception=None) -> JsonResponse:  # pragma: no cover - DEBUG=False only
    return JsonResponse(error_payload("NOT_FOUND", "请求的资源不存在"), status=404)


def handler500(request) -> JsonResponse:  # pragma: no cover - DEBUG=False only
    return JsonResponse(error_payload("INTERNAL_ERROR", "服务器内部错误"), status=500)
