"""Auth helpers for API endpoints.

The benchmark server is intended to run locally. If BENCHMARK_API_TOKEN is set,
mutating endpoints that trigger code execution require an Authorization header:

    Authorization: Bearer <token>
"""

from __future__ import annotations

import secrets

from fastapi import HTTPException, Request

from server.config import get_settings


def require_api_token(request: Request) -> None:
    token = get_settings().api_token
    if not token:
        return

    auth = (request.headers.get("Authorization") or "").strip()
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")

    provided = auth[len("Bearer ") :].strip()
    if not secrets.compare_digest(provided, token):
        raise HTTPException(status_code=401, detail="Invalid bearer token")
