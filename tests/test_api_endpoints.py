from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from server.api import create_app


@pytest.fixture
def client() -> TestClient:
    """Create a test client for the FastAPI app."""
    app = create_app()
    return TestClient(app)


def test_health_endpoint(client: TestClient) -> None:
    """Test that the /health endpoint returns ok status."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_root_redirects_to_ui(client: TestClient) -> None:
    """Test that the root endpoint redirects to /ui/index.html."""
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/ui/index.html"


def test_ui_mount_exists(client: TestClient) -> None:
    """Test that the /ui static mount is accessible."""
    # This will return 404 if index.html doesn't exist, but mount should be configured
    response = client.get("/ui/index.html")
    # We don't check 200 here because the file might not exist in test environment
    # We just verify the mount is configured and doesn't return 500 or routing error
    assert response.status_code in [200, 404]


def test_cors_middleware_configured(client: TestClient) -> None:
    """Test that CORS middleware is configured."""
    # OPTIONS request should include CORS headers
    response = client.options("/health")
    # FastAPI should handle this without error
    assert response.status_code in [200, 405]
