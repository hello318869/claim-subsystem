"""Success envelope from contract §2.3 (``code`` / ``message`` / ``data``)."""

from __future__ import annotations

from typing import Any

from rest_framework import status as http_status
from rest_framework.response import Response


def ok(
    data: Any = None,
    *,
    message: str = "操作成功",
    status: int = http_status.HTTP_200_OK,
) -> Response:
    return Response({"code": "OK", "message": message, "data": data}, status=status)


def page_payload(items: list[dict], total: int, page: int, page_size: int) -> dict:
    """Pagination envelope body from contract §2.5 (``total=0`` implies ``total_pages=0``)."""
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": (total + page_size - 1) // page_size if total else 0,
    }
