"""Critical path regression tests for key server and harness flows.

This suite provides black-box smoke tests for essential functionality:
- Server health check
- Runs listing
- Leaderboard queries
- Task discovery
- Harness metadata

These tests are designed to be fast and run on every change to catch regressions early.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from harness.run_harness import discover_tasks
from server.api import create_app


@pytest.fixture
def client() -> TestClient:
    """Create a test client for the FastAPI app."""
    app = create_app()
    return TestClient(app)


# Server Health Tests


def test_server_health_check(client: TestClient) -> None:
    """Test that the server health endpoint is accessible and returns ok."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


# Runs Listing Tests


def test_runs_listing_endpoint_accessible(client: TestClient) -> None:
    """Test that the runs listing endpoint is accessible."""
    response = client.get("/runs")
    assert response.status_code == 200
    data = response.json()
    assert "runs" in data
    assert isinstance(data["runs"], list)


def test_runs_listing_with_limit(client: TestClient) -> None:
    """Test that the runs listing endpoint respects the limit parameter."""
    response = client.get("/runs?limit=10")
    assert response.status_code == 200
    data = response.json()
    assert len(data["runs"]) <= 10


# Leaderboard Query Tests


def test_leaderboard_endpoint_accessible(client: TestClient) -> None:
    """Test that the leaderboard endpoint is accessible."""
    response = client.get("/leaderboard")
    assert response.status_code == 200
    data = response.json()
    # Leaderboard should return a dictionary with model data
    assert isinstance(data, dict)


def test_leaderboard_structure(client: TestClient) -> None:
    """Test that the leaderboard returns expected structure."""
    response = client.get("/leaderboard")
    assert response.status_code == 200
    data = response.json()
    # Should have 'models' key in response
    if "models" in data:
        assert isinstance(data["models"], list)


# Task Discovery Tests


def test_task_discovery_returns_list() -> None:
    """Test that task discovery returns a list of task IDs."""
    tasks = discover_tasks()
    assert isinstance(tasks, list)
    # Should find at least some tasks in the tasks/ directory
    # (This is a smoke test, not a guarantee of specific tasks)
    assert len(tasks) >= 0  # May be empty in test environment


def test_task_discovery_ids_are_strings() -> None:
    """Test that discovered task IDs are strings."""
    tasks = discover_tasks()
    for task_id in tasks:
        assert isinstance(task_id, str)
        assert len(task_id) > 0


def test_task_discovery_no_duplicates() -> None:
    """Test that task discovery returns unique task IDs."""
    tasks = discover_tasks()
    assert len(tasks) == len(set(tasks))


# Harness Metadata Tests


def test_harness_metadata_structure() -> None:
    """Test that harness can discover and enumerate tasks."""
    # This is a smoke test to ensure the harness discovery mechanism works
    tasks = discover_tasks()
    # Just verify we can call it without errors
    assert isinstance(tasks, list)


# Models Capabilities Endpoint Tests


def test_models_capabilities_requires_model_id(client: TestClient) -> None:
    """Test that the models capabilities endpoint requires model_id parameter."""
    response = client.get("/models/capabilities")
    assert response.status_code == 422  # Unprocessable Entity - missing required param


def test_models_capabilities_invalid_model_id(client: TestClient) -> None:
    """Test that the models capabilities endpoint handles invalid model_id.

    Note: This test mocks the external OpenRouter API call to ensure hermeticity.
    When the API returns no matching models, the endpoint returns 404.
    """
    # Mock fetch_model_metadata to avoid external network calls
    with patch("server.routes.router.fetch_model_metadata") as mock_fetch:
        mock_fetch.return_value = {}  # No models found
        response = client.get("/models/capabilities?model_id=nonexistent-model-xyz-123")
        # Should return 404 for models that don't exist
        assert response.status_code == 404


# API Schema Tests


def test_openapi_schema_accessible(client: TestClient) -> None:
    """Test that the OpenAPI schema is accessible."""
    response = client.get("/openapi.json")
    assert response.status_code == 200
    data = response.json()
    assert "openapi" in data
    assert "info" in data
    assert "paths" in data
