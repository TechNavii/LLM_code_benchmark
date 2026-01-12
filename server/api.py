from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from server.routes.router import router
from server.routes.qa_router import router as qa_router
from server.config import get_settings
from server.database import init_db
from server.qa_database import init_db as init_qa_db
from server.logging import configure_logging
from server.request_limits import RateLimitMiddleware, RequestSizeLimitMiddleware
from server.security_headers import SecurityHeadersMiddleware


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

    # Add security headers middleware (runs after CORS)
    app.add_middleware(SecurityHeadersMiddleware)

    # Add request size limit middleware (10MB default, configurable via MAX_REQUEST_BODY_SIZE)
    app.add_middleware(RequestSizeLimitMiddleware)

    # Add optional rate limiting middleware (disabled by default, enable via ENABLE_RATE_LIMITING=true)
    # Only limits POST/PUT/PATCH/DELETE requests to prevent DoS on mutating endpoints
    app.add_middleware(RateLimitMiddleware)

    app.include_router(router)
    app.include_router(qa_router)
    init_db()
    init_qa_db()
    return app


app = create_app()


__all__ = ["app", "create_app"]
