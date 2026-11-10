"""Project-level views: health probe, demo page and the contract 404 fallback."""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.db import connection
from django.http import FileResponse, Http404, HttpResponse, JsonResponse

from common.clock import iso, utcnow
from common.errors import error_payload
from config import __version__


def health(request) -> JsonResponse:
    """Readiness probe; the old FastAPI deployment exposed the same fields at ``/health``."""
    database = "ok"
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:  # noqa: BLE001 - the probe must never raise
        database = "unavailable"
    payload = {
        "status": "ok" if database == "ok" else "degraded",
        "database": database,
        "demo_mode": bool(settings.DEMO_MODE),
        "time": iso(utcnow()),
        "version": __version__,
    }
    return JsonResponse(payload, status=200 if database == "ok" else 503)


def team_page(request) -> HttpResponse:
    page = settings.FRONTEND_BUILD_DIR / "index.html"
    if not page.is_file():
        return HttpResponse(
            "请运行 start-demo.cmd，或在 frontend 目录执行 npm ci 和 npm run build。",
            content_type="text/plain; charset=utf-8",
            status=503,
        )
    return FileResponse(page.open("rb"), content_type="text/html; charset=utf-8")


def workbench_page(request) -> FileResponse:
    path: Path = settings.FRONTEND_DIR / "team.html"
    if not path.is_file():
        raise Http404("frontend/team.html 不存在")
    return FileResponse(path.open("rb"), content_type="text/html; charset=utf-8")


def api_not_found(request, *args, **kwargs) -> JsonResponse:
    """Catch-all so unknown JSON paths still use the contract's error envelope."""
    return JsonResponse(error_payload("NOT_FOUND", "请求的资源不存在"), status=404)
