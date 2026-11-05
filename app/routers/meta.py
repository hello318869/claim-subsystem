"""Health and root endpoints."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text

from app.clock import iso, utcnow
from app.config import ROOT, get_settings
from app.db import get_session_factory
from app.errors import AppError

router = APIRouter(tags=["meta"])

WEB_DIR: Path = ROOT / "web"


@router.get("/health")
def health() -> dict:
    database = "ok"
    try:
        with get_session_factory()() as session:
            session.execute(text("SELECT 1"))
    except Exception:  # pragma: no cover - only on a broken database
        database = "unavailable"
    payload = {
        "status": "ok" if database == "ok" else "degraded",
        "database": database,
        "demo_mode": get_settings().demo_mode,
        "time": iso(utcnow()),
        "version": "1.0.0",
    }
    if database != "ok":
        return JSONResponse(payload, status_code=503)
    return payload


@router.get("/", include_in_schema=False)
def index():
    candidate = WEB_DIR / "index.html"
    if candidate.is_file():
        return FileResponse(candidate)
    return {
        "service": "校园失物招领 · 失物认领子系统",
        "version": "1.0.0",
        "status": "backend-only",
        "docs": "/docs",
        "health": "/health",
        "note": "web/ 静态页面尚未就绪；接口前缀 /v1。",
    }


__all__ = ["router", "AppError"]
