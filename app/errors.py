"""Application error type and FastAPI handlers.

The error body is always ``{"code", "message", "field", "retry_after_seconds"}``.
5xx is reserved for uncaught defects; business failures use 4xx.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        field: str | None = None,
        retry_after_seconds: int | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.field = field
        self.retry_after_seconds = retry_after_seconds
        self.headers = headers or {}


def error_body(
    code: str,
    message: str,
    field: str | None = None,
    retry_after_seconds: int | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "field": field,
        "retry_after_seconds": retry_after_seconds,
    }


def _response(err: AppError) -> JSONResponse:
    headers = dict(err.headers)
    if err.retry_after_seconds is not None:
        headers.setdefault("Retry-After", str(err.retry_after_seconds))
    return JSONResponse(
        status_code=err.status_code,
        content=error_body(err.code, err.message, err.field, err.retry_after_seconds),
        headers=headers,
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return _response(exc)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        location = ".".join(str(part) for part in first.get("loc", ()) if part != "body")
        return JSONResponse(
            status_code=422,
            content=error_body("validation_error", "请求参数不合法", location or None),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "method_not_allowed"}.get(
            exc.status_code, "http_error"
        )
        return JSONResponse(status_code=exc.status_code, content=error_body(code, str(exc.detail)))

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        # Last resort: keep the frozen error body instead of a plain-text 500 page. This is
        # still counted as a defect (5xx); it only makes the failure diagnosable.
        return JSONResponse(status_code=500, content=error_body("internal_error", "服务器内部错误"))
