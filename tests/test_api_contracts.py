"""API contract tests at the HTTP boundary.

This test suite validates that API endpoints return the expected response shapes,
status codes, and handle validation errors correctly. Tests cover both code and
QA routers and are hermetic (no external network, no task execution).
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from server.api import create_app
from server.config import get_settings


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    """Create a test client for the FastAPI app without auth enabled.

    This fixture ensures BENCHMARK_API_TOKEN is unset to allow unauthenticated
    access to mutating endpoints for contract validation tests.
    """
    # Clear token and settings cache to ensure no auth is enabled
    monkeypatch.delenv("BENCHMARK_API_TOKEN", raising=False)
    get_settings.cache_clear()
    app = create_app()
    yield TestClient(app)
    # Clear cache after test for isolation
    get_settings.cache_clear()


# =============================================================================
# Code Benchmark Endpoint Contract Tests
# =============================================================================


class TestHealthEndpointContract:
    """Contract tests for /health endpoint."""

    def test_health_returns_200_with_status_ok(self, client: TestClient) -> None:
        """Test /health returns correct shape."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert "status" in data
        assert data["status"] == "ok"


class TestRunsListEndpointContract:
    """Contract tests for GET /runs endpoint."""

    def test_runs_list_returns_200_with_runs_array(self, client: TestClient) -> None:
        """Test /runs returns expected response shape."""
        response = client.get("/runs")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert "runs" in data
        assert isinstance(data["runs"], list)

    def test_runs_list_with_limit_parameter(self, client: TestClient) -> None:
        """Test /runs respects limit query parameter."""
        response = client.get("/runs?limit=5")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data["runs"], list)
        # Limit is upper bound, actual count may be less
        assert len(data["runs"]) <= 5

    def test_runs_list_run_entry_shape(self, client: TestClient) -> None:
        """Test each run entry has expected fields."""
        response = client.get("/runs")
        assert response.status_code == 200
        data = response.json()
        # If there are runs, verify shape
        for run in data["runs"]:
            assert isinstance(run, dict)
            assert "run_id" in run
            # These can be None but keys should exist
            assert "timestamp_utc" in run
            assert "model_id" in run
            assert "accuracy" in run
            assert "total_cost_usd" in run
            assert "total_duration_seconds" in run


class TestRunDetailEndpointContract:
    """Contract tests for GET /runs/{run_id} endpoint."""

    def test_run_detail_nonexistent_returns_404(self, client: TestClient) -> None:
        """Test /runs/{run_id} returns 404 for nonexistent run."""
        response = client.get("/runs/nonexistent_run_id_xyz")
        assert response.status_code == 404
        data = response.json()
        assert "detail" in data
        assert "not found" in data["detail"].lower()

    def test_run_detail_error_response_shape(self, client: TestClient) -> None:
        """Test error response has consistent shape."""
        response = client.get("/runs/missing_run")
        assert response.status_code == 404
        data = response.json()
        assert isinstance(data, dict)
        assert "detail" in data
        assert isinstance(data["detail"], str)


class TestLeaderboardEndpointContract:
    """Contract tests for GET /leaderboard endpoint."""

    def test_leaderboard_returns_200_with_models(self, client: TestClient) -> None:
        """Test /leaderboard returns expected shape."""
        response = client.get("/leaderboard")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert "models" in data
        assert isinstance(data["models"], list)

    def test_leaderboard_model_entry_shape(self, client: TestClient) -> None:
        """Test leaderboard model entries have expected fields."""
        response = client.get("/leaderboard")
        assert response.status_code == 200
        data = response.json()
        for model in data["models"]:
            assert isinstance(model, dict)
            assert "model_id" in model
            assert "thinking_level" in model
            assert "best_accuracy" in model
            assert "cost_at_best" in model
            assert "duration_at_best" in model
            assert "runs" in model


class TestModelsCapabilitiesEndpointContract:
    """Contract tests for GET /models/capabilities endpoint."""

    def test_capabilities_requires_model_id(self, client: TestClient) -> None:
        """Test /models/capabilities requires model_id parameter."""
        response = client.get("/models/capabilities")
        assert response.status_code == 422  # Pydantic validation error
        data = response.json()
        assert "detail" in data

    def test_capabilities_empty_model_id_returns_400(self, client: TestClient) -> None:
        """Test /models/capabilities with empty model_id returns 400."""
        response = client.get("/models/capabilities?model_id=")
        assert response.status_code == 400
        data = response.json()
        assert "detail" in data
        assert "model_id" in data["detail"].lower()

    def test_capabilities_whitespace_model_id_returns_400(self, client: TestClient) -> None:
        """Test /models/capabilities with whitespace model_id returns 400."""
        response = client.get("/models/capabilities?model_id=%20%20")
        assert response.status_code == 400
        data = response.json()
        assert "detail" in data

    def test_capabilities_unknown_model_returns_404(self, client: TestClient) -> None:
        """Test /models/capabilities with unknown model returns 404."""
        response = client.get("/models/capabilities?model_id=completely_unknown_model_xyz_123")
        assert response.status_code == 404
        data = response.json()
        assert "detail" in data
        assert "not found" in data["detail"].lower()

    def test_capabilities_error_response_shape(self, client: TestClient) -> None:
        """Test error responses have consistent shape."""
        response = client.get("/models/capabilities?model_id=unknown")
        assert response.status_code == 404
        data = response.json()
        assert isinstance(data, dict)
        assert "detail" in data
        assert isinstance(data["detail"], str)


class TestCreateRunValidationContract:
    """Contract tests for POST /runs input validation."""

    def test_create_run_empty_body_returns_422(self, client: TestClient) -> None:
        """Test POST /runs with empty body returns validation error."""
        response = client.post("/runs", json={})
        assert response.status_code == 422
        data = response.json()
        assert "detail" in data

    def test_create_run_missing_models_returns_422(self, client: TestClient) -> None:
        """Test POST /runs without models field returns validation error."""
        response = client.post("/runs", json={"samples": 1})
        assert response.status_code == 422
        data = response.json()
        assert "detail" in data

    def test_create_run_empty_models_array_returns_400(self, client: TestClient) -> None:
        """Test POST /runs with empty models array returns validation error."""
        response = client.post("/runs", json={"models": []})
        # Pydantic may raise 422 or custom 400 depending on validation
        assert response.status_code in (400, 422)
        data = response.json()
        assert "detail" in data

    def test_create_run_invalid_model_name_format_returns_400(self, client: TestClient) -> None:
        """Test POST /runs with invalid model name format returns 400."""
        response = client.post("/runs", json={"models": ["invalid model with spaces"]})
        assert response.status_code == 400
        data = response.json()
        assert "detail" in data

    def test_create_run_samples_out_of_range_returns_400_or_422(self, client: TestClient) -> None:
        """Test POST /runs with samples out of 1-10 range returns error."""
        # samples > 10
        response = client.post("/runs", json={"models": ["test-model"], "samples": 100})
        assert response.status_code in (400, 422)

        # samples < 1
        response = client.post("/runs", json={"models": ["test-model"], "samples": 0})
        assert response.status_code in (400, 422)

    def test_create_run_temperature_out_of_range_returns_400_or_422(self, client: TestClient) -> None:
        """Test POST /runs with temperature out of 0.0-2.0 range returns error."""
        response = client.post("/runs", json={"models": ["test-model"], "temperature": 5.0})
        assert response.status_code in (400, 422)

    def test_create_run_negative_max_tokens_returns_400_or_422(self, client: TestClient) -> None:
        """Test POST /runs with negative max_tokens returns error."""
        response = client.post("/runs", json={"models": ["test-model"], "max_tokens": -1})
        assert response.status_code in (400, 422)

    def test_create_run_invalid_provider_format_returns_400(self, client: TestClient) -> None:
        """Test POST /runs with invalid provider format returns 400."""
        response = client.post("/runs", json={"models": ["test-model"], "provider": "invalid provider!"})
        assert response.status_code == 400
        data = response.json()
        assert "detail" in data

    def test_validation_error_response_shape(self, client: TestClient) -> None:
        """Test validation error responses have expected structure."""
        response = client.post("/runs", json={})
        assert response.status_code == 422
        data = response.json()
        assert isinstance(data, dict)
        assert "detail" in data
        # FastAPI validation errors are typically lists of error objects
        assert isinstance(data["detail"], str | list)


# =============================================================================
# QA Benchmark Endpoint Contract Tests
# =============================================================================


class TestQARunsListEndpointContract:
    """Contract tests for GET /qa/runs endpoint."""

    def test_qa_runs_list_returns_200_with_runs_array(self, client: TestClient) -> None:
        """Test /qa/runs returns expected response shape."""
        response = client.get("/qa/runs")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert "runs" in data
        assert isinstance(data["runs"], list)

    def test_qa_runs_list_with_limit_parameter(self, client: TestClient) -> None:
        """Test /qa/runs respects limit query parameter."""
        response = client.get("/qa/runs?limit=5")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data["runs"], list)
        assert len(data["runs"]) <= 5

    def test_qa_runs_list_run_entry_shape(self, client: TestClient) -> None:
        """Test each QA run entry has expected fields."""
        response = client.get("/qa/runs")
        assert response.status_code == 200
        data = response.json()
        for run in data["runs"]:
            assert isinstance(run, dict)
            assert "run_id" in run
            assert "timestamp_utc" in run
            assert "model_id" in run
            assert "accuracy" in run
            assert "total_cost_usd" in run
            assert "total_duration_seconds" in run


class TestQARunDetailEndpointContract:
    """Contract tests for GET /qa/runs/{run_id} endpoint."""

    def test_qa_run_detail_nonexistent_returns_404(self, client: TestClient) -> None:
        """Test /qa/runs/{run_id} returns 404 for nonexistent run."""
        response = client.get("/qa/runs/nonexistent_run_id_xyz")
        assert response.status_code == 404
        data = response.json()
        assert "detail" in data
        assert "not found" in data["detail"].lower()

    def test_qa_run_detail_error_response_shape(self, client: TestClient) -> None:
        """Test QA error response has consistent shape."""
        response = client.get("/qa/runs/missing_run")
        assert response.status_code == 404
        data = response.json()
        assert isinstance(data, dict)
        assert "detail" in data
        assert isinstance(data["detail"], str)


class TestQALeaderboardEndpointContract:
    """Contract tests for GET /qa/leaderboard endpoint."""

    def test_qa_leaderboard_returns_200_with_models(self, client: TestClient) -> None:
        """Test /qa/leaderboard returns expected shape."""
        response = client.get("/qa/leaderboard")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert "models" in data
        assert isinstance(data["models"], list)


class TestQACreateRunValidationContract:
    """Contract tests for POST /qa/runs input validation."""

    def test_qa_create_run_empty_body_returns_422(self, client: TestClient) -> None:
        """Test POST /qa/runs with empty body returns validation error."""
        response = client.post("/qa/runs", json={})
        assert response.status_code == 422
        data = response.json()
        assert "detail" in data

    def test_qa_create_run_missing_models_returns_422(self, client: TestClient) -> None:
        """Test POST /qa/runs without models field returns validation error."""
        response = client.post("/qa/runs", json={"samples": 1})
        assert response.status_code == 422
        data = response.json()
        assert "detail" in data

    def test_qa_create_run_empty_models_array_returns_422(self, client: TestClient) -> None:
        """Test POST /qa/runs with empty models array returns validation error."""
        response = client.post("/qa/runs", json={"models": []})
        assert response.status_code == 422
        data = response.json()
        assert "detail" in data

    def test_qa_create_run_whitespace_only_model_returns_422(self, client: TestClient) -> None:
        """Test POST /qa/runs with whitespace-only model returns validation error."""
        response = client.post("/qa/runs", json={"models": ["  ", "   "]})
        assert response.status_code == 422
        data = response.json()
        assert "detail" in data

    def test_qa_create_run_zero_samples_returns_422(self, client: TestClient) -> None:
        """Test POST /qa/runs with samples=0 returns validation error."""
        response = client.post("/qa/runs", json={"models": ["test-model"], "samples": 0})
        assert response.status_code == 422
        data = response.json()
        assert "detail" in data

    def test_qa_create_run_negative_max_tokens_returns_422(self, client: TestClient) -> None:
        """Test POST /qa/runs with negative max_tokens returns validation error."""
        response = client.post("/qa/runs", json={"models": ["test-model"], "max_tokens": -100})
        assert response.status_code == 422
        data = response.json()
        assert "detail" in data

    def test_qa_create_run_invalid_provider_format_returns_422(self, client: TestClient) -> None:
        """Test POST /qa/runs with invalid provider format returns validation error."""
        response = client.post("/qa/runs", json={"models": ["test-model"], "provider": "has space!"})
        assert response.status_code == 422
        data = response.json()
        assert "detail" in data


# =============================================================================
# Error Response Consistency Tests
# =============================================================================


class TestErrorResponseConsistency:
    """Tests for consistent error response format across endpoints."""

    def test_404_responses_have_detail_field(self, client: TestClient) -> None:
        """Test all 404 responses include a detail field."""
        endpoints = [
            "/runs/nonexistent_run",
            "/qa/runs/nonexistent_run",
            "/models/capabilities?model_id=unknown_model",
        ]
        for endpoint in endpoints:
            response = client.get(endpoint)
            assert response.status_code == 404, f"Expected 404 for {endpoint}"
            data = response.json()
            assert "detail" in data, f"Missing 'detail' in 404 for {endpoint}"

    def test_422_responses_have_detail_field(self, client: TestClient) -> None:
        """Test all 422 responses include a detail field."""
        # Missing required fields triggers 422
        test_cases: list[tuple[str, dict[str, Any]]] = [
            ("/runs", {}),
            ("/qa/runs", {}),
        ]
        for endpoint, body in test_cases:
            response = client.post(endpoint, json=body)
            assert response.status_code == 422, f"Expected 422 for {endpoint}"
            data = response.json()
            assert "detail" in data, f"Missing 'detail' in 422 for {endpoint}"


# =============================================================================
# Response Type Validation Tests
# =============================================================================


class TestResponseTypeValidation:
    """Tests validating response field types match expected contracts."""

    def test_health_status_is_string(self, client: TestClient) -> None:
        """Test /health status field is a string."""
        response = client.get("/health")
        data = response.json()
        assert isinstance(data["status"], str)

    def test_runs_list_run_id_is_string(self, client: TestClient) -> None:
        """Test run_id in /runs list is always a string."""
        response = client.get("/runs")
        data = response.json()
        for run in data["runs"]:
            assert isinstance(run["run_id"], str)

    def test_leaderboard_runs_count_is_int(self, client: TestClient) -> None:
        """Test runs count in leaderboard is an integer."""
        response = client.get("/leaderboard")
        data = response.json()
        for model in data["models"]:
            assert isinstance(model["runs"], int)

    def test_qa_runs_list_run_id_is_string(self, client: TestClient) -> None:
        """Test run_id in /qa/runs list is always a string."""
        response = client.get("/qa/runs")
        data = response.json()
        for run in data["runs"]:
            assert isinstance(run["run_id"], str)


# =============================================================================
# Edge Cases and Boundary Tests
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_runs_list_limit_zero(self, client: TestClient) -> None:
        """Test /runs with limit=0 is handled."""
        response = client.get("/runs?limit=0")
        # Should still return 200, possibly empty or interpreted as default
        assert response.status_code == 200
        data = response.json()
        assert "runs" in data

    def test_runs_list_limit_negative(self, client: TestClient) -> None:
        """Test /runs with negative limit is handled."""
        response = client.get("/runs?limit=-1")
        # FastAPI may reject or ignore; either way should not crash
        assert response.status_code in (200, 422)

    def test_runs_list_limit_very_large(self, client: TestClient) -> None:
        """Test /runs with very large limit is handled."""
        response = client.get("/runs?limit=999999")
        assert response.status_code == 200
        data = response.json()
        assert "runs" in data

    def test_run_id_with_special_characters(self, client: TestClient) -> None:
        """Test /runs/{run_id} with special characters in path."""
        # URL-encoded special chars
        response = client.get("/runs/run%20with%20spaces")
        assert response.status_code == 404  # Not found, but should not crash

    def test_empty_model_id_capabilities(self, client: TestClient) -> None:
        """Test /models/capabilities with various empty inputs."""
        # Empty string
        response = client.get("/models/capabilities?model_id=")
        assert response.status_code == 400

    def test_qa_runs_list_limit_zero(self, client: TestClient) -> None:
        """Test /qa/runs with limit=0 is handled."""
        response = client.get("/qa/runs?limit=0")
        assert response.status_code == 200
        data = response.json()
        assert "runs" in data


# =============================================================================
# Retry/Resume Endpoint Contract Tests (404 for missing runs)
# =============================================================================


class TestRetryResumeEndpointsContract:
    """Contract tests for retry and resume endpoints."""

    def test_api_errors_endpoint_missing_run_returns_404(self, client: TestClient) -> None:
        """Test /runs/{run_id}/api-errors returns 404 for missing run."""
        response = client.get("/runs/nonexistent_run/api-errors")
        assert response.status_code == 404
        data = response.json()
        assert "detail" in data

    def test_incomplete_endpoint_missing_run_returns_404(self, client: TestClient) -> None:
        """Test /runs/{run_id}/incomplete returns 404 for missing run."""
        response = client.get("/runs/nonexistent_run/incomplete")
        assert response.status_code == 404
        data = response.json()
        assert "detail" in data

    def test_qa_api_errors_endpoint_missing_run_returns_404(self, client: TestClient) -> None:
        """Test /qa/runs/{run_id}/api-errors returns 404 for missing run."""
        response = client.get("/qa/runs/nonexistent_run/api-errors")
        assert response.status_code == 404
        data = response.json()
        assert "detail" in data


# =============================================================================
# OpenAPI Schema Contract Tests
# =============================================================================


class TestOpenAPISchemaContract:
    """Contract tests for OpenAPI schema availability and structure."""

    def test_openapi_schema_accessible(self, client: TestClient) -> None:
        """Test /openapi.json is accessible."""
        response = client.get("/openapi.json")
        assert response.status_code == 200

    def test_openapi_schema_has_required_fields(self, client: TestClient) -> None:
        """Test OpenAPI schema has required top-level fields."""
        response = client.get("/openapi.json")
        data = response.json()
        assert "openapi" in data
        assert "info" in data
        assert "paths" in data

    def test_openapi_schema_version(self, client: TestClient) -> None:
        """Test OpenAPI schema uses version 3.x."""
        response = client.get("/openapi.json")
        data = response.json()
        assert data["openapi"].startswith("3.")

    def test_openapi_paths_include_core_endpoints(self, client: TestClient) -> None:
        """Test OpenAPI schema includes core endpoints."""
        response = client.get("/openapi.json")
        data = response.json()
        paths = data["paths"]
        # Core code benchmark endpoints
        assert "/health" in paths
        assert "/runs" in paths
        assert "/leaderboard" in paths
        assert "/models/capabilities" in paths
        # Core QA endpoints
        assert "/qa/runs" in paths
        assert "/qa/leaderboard" in paths
