from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from server.config import get_settings
from server.routes.auth import require_api_token


def _clear_settings_cache() -> None:
    get_settings.cache_clear()


def test_require_api_token_allows_when_unset(monkeypatch) -> None:
    monkeypatch.delenv("BENCHMARK_API_TOKEN", raising=False)
    _clear_settings_cache()

    app = FastAPI()

    @app.get("/protected")
    def protected(_: None = Depends(require_api_token)) -> dict[str, bool]:
        return {"ok": True}

    client = TestClient(app)
    resp = client.get("/protected")
    assert resp.status_code == 200


def test_require_api_token_blocks_when_missing(monkeypatch) -> None:
    monkeypatch.setenv("BENCHMARK_API_TOKEN", "secret")
    _clear_settings_cache()

    app = FastAPI()

    @app.get("/protected")
    def protected(_: None = Depends(require_api_token)) -> dict[str, bool]:
        return {"ok": True}

    client = TestClient(app)
    resp = client.get("/protected")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Missing bearer token"


def test_require_api_token_blocks_when_invalid(monkeypatch) -> None:
    monkeypatch.setenv("BENCHMARK_API_TOKEN", "secret")
    _clear_settings_cache()

    app = FastAPI()

    @app.get("/protected")
    def protected(_: None = Depends(require_api_token)) -> dict[str, bool]:
        return {"ok": True}

    client = TestClient(app)
    resp = client.get("/protected", headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid bearer token"


def test_require_api_token_allows_when_valid(monkeypatch) -> None:
    monkeypatch.setenv("BENCHMARK_API_TOKEN", "secret")
    _clear_settings_cache()

    app = FastAPI()

    @app.get("/protected")
    def protected(_: None = Depends(require_api_token)) -> dict[str, bool]:
        return {"ok": True}

    client = TestClient(app)
    resp = client.get("/protected", headers={"Authorization": "Bearer secret"})
    assert resp.status_code == 200


def test_mutating_routes_are_protected_by_dependency() -> None:
    from server.routes.router import router as code_router
    from server.routes.qa_router import router as qa_router

    app = FastAPI()
    app.include_router(code_router)
    app.include_router(qa_router)

    protected = [
        ("/runs", "POST"),
        ("/leaderboard/{model_id:path}", "DELETE"),
        ("/runs/{run_id}/retry-api-errors", "POST"),
        ("/runs/{run_id}/retry-single", "POST"),
        ("/runs/{run_id}/resume", "POST"),
        ("/qa/runs", "POST"),
        ("/qa/leaderboard/{model_id:path}", "DELETE"),
        ("/qa/runs/{run_id}/retry-api-errors", "POST"),
        ("/qa/runs/{run_id}/retry-single", "POST"),
    ]

    for path, method in protected:
        route = next(r for r in app.routes if isinstance(r, APIRoute) and r.path == path and method in r.methods)
        assert any(dep.call is require_api_token for dep in route.dependant.dependencies)
