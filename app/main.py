"""Application entry point.

``app.main:app`` is the single uvicorn target used by the demo and by tests. ``create_app``
exists so tests can build an isolated instance without touching module-level state.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import ROOT
from app.errors import install_error_handlers
from app.routers import chat, claims, demo, listings, matches, meta

WEB_DIR = ROOT / "web"
API_PREFIX = "/v1"


def create_app() -> FastAPI:
    application = FastAPI(
        title="校园失物招领 · 失物认领子系统",
        version="1.0.0",
        description=(
            "认领管理、匿名沟通、可解释规则匹配。只读其他成员发布的招领/失物快照，"
            "不实现发布、账号注册与管理裁决。"
        ),
    )
    install_error_handlers(application)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Idempotent-Replay", "Retry-After"],
    )

    application.include_router(meta.router)
    for router in (demo.router, listings.router, claims.router, chat.router, matches.router):
        application.include_router(router, prefix=API_PREFIX)

    # Static files are mounted even before web/ exists so a later front-end drop-in needs
    # no code change (only a restart). Directories are not modified here.
    application.mount(
        "/static",
        StaticFiles(directory=str(WEB_DIR), check_dir=False),
        name="static",
    )
    return application


app = create_app()
