"""Auth permission matrix tests for BENCHMARK_API_TOKEN across all endpoints.

This module tests that:
1. Mutating endpoints (POST/DELETE) require auth when BENCHMARK_API_TOKEN is set
2. Read-only endpoints (GET) remain accessible without a token
3. Correct tokens allow access (200/202)
4. Missing or invalid tokens are rejected (401)

Endpoints covered:
- Code router: /runs, /leaderboard, /runs/{id}/retry-*, /runs/{id}/resume
- QA router: /qa/runs, /qa/leaderboard, /qa/runs/{id}/retry-*
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from server.config import get_settings
from server.api import create_app


def _clear_settings_cache() -> None:
    get_settings.cache_clear()


@pytest.fixture
def client_with_token(monkeypatch):
    """Create a test client with BENCHMARK_API_TOKEN enabled."""
    monkeypatch.setenv("BENCHMARK_API_TOKEN", "test-secret-token")
    _clear_settings_cache()
    app = create_app()
    yield TestClient(app)
    _clear_settings_cache()


@pytest.fixture
def client_without_token(monkeypatch):
    """Create a test client without BENCHMARK_API_TOKEN."""
    monkeypatch.delenv("BENCHMARK_API_TOKEN", raising=False)
    _clear_settings_cache()
    app = create_app()
    yield TestClient(app)
    _clear_settings_cache()


# =============================================================================
# Tests: Mutating endpoints require auth when token is set
# =============================================================================


class TestMutatingEndpointsMissingToken:
    """Test that mutating endpoints return 401 when auth header is missing."""

    def test_post_runs_missing_token(self, client_with_token: TestClient) -> None:
        resp = client_with_token.post("/runs", json={"models": ["test-model"]})
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Missing bearer token"

    def test_delete_leaderboard_missing_token(self, client_with_token: TestClient) -> None:
        resp = client_with_token.delete("/leaderboard/test-model")
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Missing bearer token"

    def test_post_retry_api_errors_missing_token(self, client_with_token: TestClient) -> None:
        resp = client_with_token.post("/runs/fake-run-id/retry-api-errors")
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Missing bearer token"

    def test_post_retry_single_missing_token(self, client_with_token: TestClient) -> None:
        resp = client_with_token.post(
            "/runs/fake-run-id/retry-single",
            json={"task_id": "test-task"},
        )
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Missing bearer token"

    def test_post_resume_missing_token(self, client_with_token: TestClient) -> None:
        resp = client_with_token.post("/runs/fake-run-id/resume")
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Missing bearer token"

    def test_qa_post_runs_missing_token(self, client_with_token: TestClient) -> None:
        resp = client_with_token.post("/qa/runs", json={"models": ["test-model"]})
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Missing bearer token"

    def test_qa_delete_leaderboard_missing_token(self, client_with_token: TestClient) -> None:
        resp = client_with_token.delete("/qa/leaderboard/test-model")
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Missing bearer token"

    def test_qa_post_retry_api_errors_missing_token(self, client_with_token: TestClient) -> None:
        resp = client_with_token.post("/qa/runs/fake-run-id/retry-api-errors")
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Missing bearer token"

    def test_qa_post_retry_single_missing_token(self, client_with_token: TestClient) -> None:
        resp = client_with_token.post(
            "/qa/runs/fake-run-id/retry-single",
            json={"question_number": 1},
        )
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Missing bearer token"


class TestMutatingEndpointsInvalidToken:
    """Test that mutating endpoints return 401 with an incorrect token."""

    def _headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer wrong-token"}

    def test_post_runs_invalid_token(self, client_with_token: TestClient) -> None:
        resp = client_with_token.post(
            "/runs",
            json={"models": ["test-model"]},
            headers=self._headers(),
        )
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid bearer token"

    def test_delete_leaderboard_invalid_token(self, client_with_token: TestClient) -> None:
        resp = client_with_token.delete("/leaderboard/test-model", headers=self._headers())
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid bearer token"

    def test_post_retry_api_errors_invalid_token(self, client_with_token: TestClient) -> None:
        resp = client_with_token.post(
            "/runs/fake-run-id/retry-api-errors",
            headers=self._headers(),
        )
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid bearer token"

    def test_post_retry_single_invalid_token(self, client_with_token: TestClient) -> None:
        resp = client_with_token.post(
            "/runs/fake-run-id/retry-single",
            json={"task_id": "test-task"},
            headers=self._headers(),
        )
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid bearer token"

    def test_post_resume_invalid_token(self, client_with_token: TestClient) -> None:
        resp = client_with_token.post(
            "/runs/fake-run-id/resume",
            headers=self._headers(),
        )
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid bearer token"

    def test_qa_post_runs_invalid_token(self, client_with_token: TestClient) -> None:
        resp = client_with_token.post(
            "/qa/runs",
            json={"models": ["test-model"]},
            headers=self._headers(),
        )
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid bearer token"

    def test_qa_delete_leaderboard_invalid_token(self, client_with_token: TestClient) -> None:
        resp = client_with_token.delete("/qa/leaderboard/test-model", headers=self._headers())
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid bearer token"

    def test_qa_post_retry_api_errors_invalid_token(self, client_with_token: TestClient) -> None:
        resp = client_with_token.post(
            "/qa/runs/fake-run-id/retry-api-errors",
            headers=self._headers(),
        )
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid bearer token"

    def test_qa_post_retry_single_invalid_token(self, client_with_token: TestClient) -> None:
        resp = client_with_token.post(
            "/qa/runs/fake-run-id/retry-single",
            json={"question_number": 1},
            headers=self._headers(),
        )
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid bearer token"


class TestMutatingEndpointsCorrectToken:
    """Test that mutating endpoints accept a correct token.

    Note: These tests verify auth passes (not 401), but the request may fail
    for other reasons (404 for missing run_id, 400 for invalid input, etc.).
    The key assertion is that we DO NOT get 401.
    """

    def _headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer test-secret-token"}

    def test_post_runs_correct_token(self, client_with_token: TestClient) -> None:
        resp = client_with_token.post(
            "/runs",
            json={"models": ["test-model"]},
            headers=self._headers(),
        )
        # Should not be 401 - may be 400/500 if model is invalid or harness fails
        assert resp.status_code != 401

    def test_delete_leaderboard_correct_token(self, client_with_token: TestClient) -> None:
        resp = client_with_token.delete(
            "/leaderboard/nonexistent-model",
            headers=self._headers(),
        )
        # Should succeed (200) even if model doesn't exist (returns already_missing)
        assert resp.status_code == 200
        assert resp.json()["status"] in ("removed", "already_missing")

    def test_post_retry_api_errors_correct_token(self, client_with_token: TestClient) -> None:
        resp = client_with_token.post(
            "/runs/nonexistent-run-id/retry-api-errors",
            headers=self._headers(),
        )
        # Should be 404 (run not found), not 401
        assert resp.status_code == 404
        assert "Run not found" in resp.json()["detail"]

    def test_post_retry_single_correct_token(self, client_with_token: TestClient) -> None:
        resp = client_with_token.post(
            "/runs/nonexistent-run-id/retry-single",
            json={"task_id": "test-task"},
            headers=self._headers(),
        )
        # Should be 404 (run not found), not 401
        assert resp.status_code == 404

    def test_post_resume_correct_token(self, client_with_token: TestClient) -> None:
        resp = client_with_token.post(
            "/runs/nonexistent-run-id/resume",
            headers=self._headers(),
        )
        # Should be 404 (run directory not found), not 401
        assert resp.status_code == 404

    def test_qa_post_runs_correct_token(self, client_with_token: TestClient) -> None:
        resp = client_with_token.post(
            "/qa/runs",
            json={"models": ["test-model"]},
            headers=self._headers(),
        )
        # Should not be 401 - may be 500 if questions can't load
        assert resp.status_code != 401

    def test_qa_delete_leaderboard_correct_token(self, client_with_token: TestClient) -> None:
        resp = client_with_token.delete(
            "/qa/leaderboard/nonexistent-model",
            headers=self._headers(),
        )
        # Should succeed (200) even if model doesn't exist
        assert resp.status_code == 200
        assert resp.json()["status"] in ("removed", "already_missing")

    def test_qa_post_retry_api_errors_correct_token(self, client_with_token: TestClient) -> None:
        resp = client_with_token.post(
            "/qa/runs/nonexistent-run-id/retry-api-errors",
            headers=self._headers(),
        )
        # Should be 404 (run not found), not 401
        assert resp.status_code == 404

    def test_qa_post_retry_single_correct_token(self, client_with_token: TestClient) -> None:
        resp = client_with_token.post(
            "/qa/runs/nonexistent-run-id/retry-single",
            json={"question_number": 1},
            headers=self._headers(),
        )
        # Should be 404 (run not found), not 401
        assert resp.status_code == 404


# =============================================================================
# Tests: Mutating endpoints work without token when BENCHMARK_API_TOKEN unset
# =============================================================================


class TestMutatingEndpointsNoTokenRequired:
    """Test that mutating endpoints work when BENCHMARK_API_TOKEN is not set."""

    def test_post_runs_no_token_required(self, client_without_token: TestClient) -> None:
        resp = client_without_token.post("/runs", json={"models": ["test-model"]})
        # Should not be 401 - may fail for other reasons
        assert resp.status_code != 401

    def test_delete_leaderboard_no_token_required(self, client_without_token: TestClient) -> None:
        resp = client_without_token.delete("/leaderboard/test-model")
        assert resp.status_code == 200

    def test_post_retry_api_errors_no_token_required(self, client_without_token: TestClient) -> None:
        resp = client_without_token.post("/runs/fake-run-id/retry-api-errors")
        # 404 (not 401) - no auth required
        assert resp.status_code == 404

    def test_post_retry_single_no_token_required(self, client_without_token: TestClient) -> None:
        resp = client_without_token.post(
            "/runs/fake-run-id/retry-single",
            json={"task_id": "test-task"},
        )
        assert resp.status_code == 404

    def test_post_resume_no_token_required(self, client_without_token: TestClient) -> None:
        resp = client_without_token.post("/runs/fake-run-id/resume")
        assert resp.status_code == 404

    def test_qa_post_runs_no_token_required(self, client_without_token: TestClient) -> None:
        resp = client_without_token.post("/qa/runs", json={"models": ["test-model"]})
        assert resp.status_code != 401

    def test_qa_delete_leaderboard_no_token_required(self, client_without_token: TestClient) -> None:
        resp = client_without_token.delete("/qa/leaderboard/test-model")
        assert resp.status_code == 200

    def test_qa_post_retry_api_errors_no_token_required(self, client_without_token: TestClient) -> None:
        resp = client_without_token.post("/qa/runs/fake-run-id/retry-api-errors")
        assert resp.status_code == 404

    def test_qa_post_retry_single_no_token_required(self, client_without_token: TestClient) -> None:
        resp = client_without_token.post(
            "/qa/runs/fake-run-id/retry-single",
            json={"question_number": 1},
        )
        assert resp.status_code == 404


# =============================================================================
# Tests: Read-only endpoints remain accessible without a token
# =============================================================================


class TestReadOnlyEndpointsAccessibleWithToken:
    """Test that read-only GET endpoints work without auth header when token is set."""

    def test_health_accessible(self, client_with_token: TestClient) -> None:
        resp = client_with_token.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_list_runs_accessible(self, client_with_token: TestClient) -> None:
        resp = client_with_token.get("/runs")
        assert resp.status_code == 200
        assert "runs" in resp.json()

    def test_get_run_accessible(self, client_with_token: TestClient) -> None:
        resp = client_with_token.get("/runs/nonexistent")
        # 404 is expected (run not found), not 401
        assert resp.status_code == 404

    def test_leaderboard_accessible(self, client_with_token: TestClient) -> None:
        resp = client_with_token.get("/leaderboard")
        assert resp.status_code == 200
        assert "models" in resp.json()

    def test_model_capabilities_accessible(self, client_with_token: TestClient) -> None:
        # Empty model_id returns 400, not 401
        resp = client_with_token.get("/models/capabilities", params={"model_id": ""})
        assert resp.status_code == 400

    def test_run_api_errors_accessible(self, client_with_token: TestClient) -> None:
        resp = client_with_token.get("/runs/nonexistent/api-errors")
        # 404 (run not found), not 401
        assert resp.status_code == 404

    def test_run_incomplete_accessible(self, client_with_token: TestClient) -> None:
        resp = client_with_token.get("/runs/nonexistent/incomplete")
        # 404 (run directory not found), not 401
        assert resp.status_code == 404

    def test_qa_list_runs_accessible(self, client_with_token: TestClient) -> None:
        resp = client_with_token.get("/qa/runs")
        assert resp.status_code == 200
        assert "runs" in resp.json()

    def test_qa_get_run_accessible(self, client_with_token: TestClient) -> None:
        resp = client_with_token.get("/qa/runs/nonexistent")
        assert resp.status_code == 404

    def test_qa_leaderboard_accessible(self, client_with_token: TestClient) -> None:
        resp = client_with_token.get("/qa/leaderboard")
        assert resp.status_code == 200
        assert "models" in resp.json()

    def test_qa_run_api_errors_accessible(self, client_with_token: TestClient) -> None:
        resp = client_with_token.get("/qa/runs/nonexistent/api-errors")
        assert resp.status_code == 404


class TestReadOnlyEndpointsAccessibleWithoutToken:
    """Test that read-only GET endpoints work when no token is configured."""

    def test_health_accessible(self, client_without_token: TestClient) -> None:
        resp = client_without_token.get("/health")
        assert resp.status_code == 200

    def test_list_runs_accessible(self, client_without_token: TestClient) -> None:
        resp = client_without_token.get("/runs")
        assert resp.status_code == 200

    def test_get_run_accessible(self, client_without_token: TestClient) -> None:
        resp = client_without_token.get("/runs/nonexistent")
        assert resp.status_code == 404

    def test_leaderboard_accessible(self, client_without_token: TestClient) -> None:
        resp = client_without_token.get("/leaderboard")
        assert resp.status_code == 200

    def test_run_api_errors_accessible(self, client_without_token: TestClient) -> None:
        resp = client_without_token.get("/runs/nonexistent/api-errors")
        assert resp.status_code == 404

    def test_run_incomplete_accessible(self, client_without_token: TestClient) -> None:
        resp = client_without_token.get("/runs/nonexistent/incomplete")
        assert resp.status_code == 404

    def test_qa_list_runs_accessible(self, client_without_token: TestClient) -> None:
        resp = client_without_token.get("/qa/runs")
        assert resp.status_code == 200

    def test_qa_get_run_accessible(self, client_without_token: TestClient) -> None:
        resp = client_without_token.get("/qa/runs/nonexistent")
        assert resp.status_code == 404

    def test_qa_leaderboard_accessible(self, client_without_token: TestClient) -> None:
        resp = client_without_token.get("/qa/leaderboard")
        assert resp.status_code == 200

    def test_qa_run_api_errors_accessible(self, client_without_token: TestClient) -> None:
        resp = client_without_token.get("/qa/runs/nonexistent/api-errors")
        assert resp.status_code == 404


# =============================================================================
# Additional edge cases for auth token formats
# =============================================================================


class TestAuthTokenEdgeCases:
    """Test edge cases for token format handling."""

    def test_bearer_case_insensitivity(self, client_with_token: TestClient) -> None:
        # The auth implementation expects exact "Bearer " prefix
        resp = client_with_token.get("/runs")
        assert resp.status_code == 200  # GET doesn't require auth

        # POST does require auth - test with lowercase "bearer"
        resp = client_with_token.post(
            "/runs",
            json={"models": ["test"]},
            headers={"Authorization": "bearer test-secret-token"},
        )
        # Lowercase 'bearer' is rejected (implementation uses startswith("Bearer "))
        assert resp.status_code == 401

    def test_token_with_extra_whitespace(self, client_with_token: TestClient) -> None:
        # Token with leading/trailing whitespace in value
        resp = client_with_token.delete(
            "/leaderboard/test-model",
            headers={"Authorization": "Bearer  test-secret-token "},
        )
        # The implementation strips whitespace from the provided token
        assert resp.status_code == 200

    def test_empty_bearer_token(self, client_with_token: TestClient) -> None:
        resp = client_with_token.post(
            "/runs",
            json={"models": ["test"]},
            headers={"Authorization": "Bearer "},
        )
        assert resp.status_code == 401

    def test_no_space_after_bearer(self, client_with_token: TestClient) -> None:
        resp = client_with_token.post(
            "/runs",
            json={"models": ["test"]},
            headers={"Authorization": "Bearertest-secret-token"},
        )
        assert resp.status_code == 401

    def test_basic_auth_rejected(self, client_with_token: TestClient) -> None:
        # Basic auth should not work
        import base64

        creds = base64.b64encode(b"user:test-secret-token").decode()
        resp = client_with_token.post(
            "/runs",
            json={"models": ["test"]},
            headers={"Authorization": f"Basic {creds}"},
        )
        assert resp.status_code == 401
