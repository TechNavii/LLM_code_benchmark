from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from server.api.router import router
from server.config import get_settings
from server.database import init_db
from server.logging import configure_logging


ROOT = Path(__file__).resolve().parents[1]


def load_env(path: Path) -> None:
    """Populate os.environ from a dotenv-style file if variables are missing."""

    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip()


def create_app() -> FastAPI:
    """Initialise and configure the FastAPI application."""

    load_env(ROOT / ".env")

    settings = get_settings()
    configure_logging()

    app = FastAPI(title="Benchmark Harness API")
    app.mount("/ui", StaticFiles(directory=str(ROOT / "gui"), html=True), name="ui")
    app.mount(
        "/artifacts",
        StaticFiles(directory=str(ROOT / "runs"), check_dir=False),
        name="artifacts",
    )

    cors_origins = settings.cors_origins or settings.api.cors_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)
    init_db()
    return app


app = create_app()


__all__ = ["app", "create_app"]