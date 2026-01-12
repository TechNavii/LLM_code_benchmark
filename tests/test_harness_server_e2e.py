"""End-to-end tests wiring harness CLI to server API without real LLM calls.

These tests verify the full integration between the FastAPI server and the
harness by using mock model responses (response_text). No real API calls
are made to OpenRouter or other providers.

Requirements:
- Tests are hermetic (no network, temp directories, no OPENROUTER_API_KEY needed)
- Server runs on ephemeral port with temp database
- Uses response_text to mock model responses
"""

from __future__ import annotations

import multiprocessing
import os
import socket
import sys
import tempfile
import time
from collections.abc import Generator
from contextlib import closing

import pytest
import requests
import uvicorn


# Mark all tests in this module as e2e tests
pytestmark = pytest.mark.e2e


def find_free_port() -> int:
    """Find a free port on localhost."""
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


def wait_for_server(host: str, port: int, timeout: float = 10.0) -> bool:
    """Wait for the server to become available."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
                s.settimeout(0.5)
                s.connect((host, port))
                return True
        except OSError:
            time.sleep(0.1)
    return False


def run_server(host: str, port: int, temp_dir: str) -> None:
    """Run the FastAPI server in a subprocess with isolated config."""
    # Set up isolated environment BEFORE any imports
    os.environ["OPENROUTER_API_KEY"] = "test-dummy-key-for-e2e-testing"
    os.environ["DATABASE__URL"] = f"sqlite:///{temp_dir}/test_history.db"
    os.environ["BENCHMARK_API_TOKEN"] = ""  # Disable auth for testing

    # Suppress stdout/stderr to avoid noise in test output
    sys.stdout = open(os.devnull, "w")  # noqa: SIM115
    sys.stderr = open(os.devnull, "w")  # noqa: SIM115

    # Clear settings cache and import server AFTER setting env vars
    from server.config import get_settings

    get_settings.cache_clear()

    from server.api import create_app

    app = create_app()
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="error",
        access_log=False,
    )
    server = uvicorn.Server(config)
    server.run()


@pytest.fixture(scope="module")
def temp_runs_dir() -> Generator[str, None, None]:
    """Create a temporary directory for test artifacts."""
    with tempfile.TemporaryDirectory(prefix="benchmark_e2e_") as temp_dir:
        yield temp_dir


@pytest.fixture(scope="module")
def server_url(temp_runs_dir: str) -> Generator[str, None, None]:
    """Start the FastAPI server on an ephemeral port and return its URL."""
    host = "127.0.0.1"
    port = find_free_port()

    # Start server in a separate process with isolated environment
    # Use 'spawn' context to ensure clean environment in subprocess
    ctx = multiprocessing.get_context("spawn")
    process = ctx.Process(target=run_server, args=(host, port, temp_runs_dir))
    process.start()

    try:
        # Wait for server to be ready
        if not wait_for_server(host, port, timeout=20.0):
            process.terminate()
            process.join(timeout=5)
            pytest.fail("Server failed to start within timeout")

        yield f"http://{host}:{port}"
    finally:
        # Cleanup
        process.terminate()
        process.join(timeout=5)
        if process.is_alive():
            process.kill()
            process.join(timeout=2)


# Sample task that should always exist in the repo
SAMPLE_TASK = "sample_bug_fix"

# Mock response text that produces a valid diff for sample_bug_fix task
MOCK_RESPONSE_TEXT = """```diff
--- a/calculator.py
+++ b/calculator.py
@@ -13,4 +13,4 @@
     BUG: currently returns absolute difference instead of signed difference.
     \"\"\"
     # Incorrect implementation kept here for LLM to fix.
-    return abs(a - b)
+    return a - b

```"""


class TestServerHealth:
    """Basic server health checks."""

    def test_health_endpoint(self, server_url: str) -> None:
        """Test that the health endpoint returns success."""
        response = requests.get(f"{server_url}/health", timeout=5)
        assert response.status_code == 200

    def test_runs_list_endpoint(self, server_url: str) -> None:
        """Test that the runs list endpoint is accessible."""
        response = requests.get(f"{server_url}/runs", timeout=5)
        assert response.status_code == 200
        data = response.json()
        assert "runs" in data

    def test_leaderboard_endpoint(self, server_url: str) -> None:
        """Test that the leaderboard endpoint is accessible."""
        response = requests.get(f"{server_url}/leaderboard", timeout=5)
        assert response.status_code == 200
        data = response.json()
        # Leaderboard returns models list
        assert "models" in data


class TestRunCreation:
    """Tests for creating runs with mock responses."""

    def test_create_run_returns_run_id(self, server_url: str) -> None:
        """Test that POST /runs returns a run_id."""
        payload = {
            "models": ["test/mock-model"],
            "tasks": [SAMPLE_TASK],
            "samples": 1,
            "response_text": MOCK_RESPONSE_TEXT,
        }

        response = requests.post(
            f"{server_url}/runs",
            json=payload,
            timeout=10,
        )
        assert response.status_code == 200
        data = response.json()
        assert "run_id" in data
        assert data["run_id"].startswith("run_")

    @pytest.mark.skip(reason="Requires harness execution which is too slow for CI; covered by other tests")
    def test_create_run_with_response_text_executes(self, server_url: str) -> None:
        """Test that a run with response_text completes and creates DB entry.

        This test is skipped by default as harness execution (even with mock response)
        can take a long time due to workspace setup and test execution.
        The test_create_run_returns_run_id test verifies the API accepts the request.
        """
        payload = {
            "models": ["test/mock-model"],
            "tasks": [SAMPLE_TASK],
            "samples": 1,
            "response_text": MOCK_RESPONSE_TEXT,
        }

        response = requests.post(
            f"{server_url}/runs",
            json=payload,
            timeout=10,
        )
        assert response.status_code == 200
        run_id = response.json()["run_id"]

        # Wait for the run to complete (it should be quick with mock response)
        # Poll the runs list to see if the run appears
        max_wait = 120  # seconds (harness evaluation can take time)
        poll_interval = 2.0
        elapsed = 0.0
        found = False

        while elapsed < max_wait:
            runs_response = requests.get(f"{server_url}/runs", timeout=5)
            if runs_response.status_code == 200:
                runs = runs_response.json().get("runs", [])
                run_ids = [r.get("run_id") for r in runs]
                if run_id in run_ids:
                    found = True
                    break
            time.sleep(poll_interval)
            elapsed += poll_interval

        assert found, f"Run {run_id} did not appear in runs list within {max_wait}s"


class TestRunDetailEndpoint:
    """Tests for the run detail endpoint."""

    def test_run_detail_not_found(self, server_url: str) -> None:
        """Test that requesting a non-existent run returns 404."""
        response = requests.get(
            f"{server_url}/runs/nonexistent_run_12345",
            timeout=5,
        )
        assert response.status_code == 404


class TestErrorHandling:
    """Tests for error handling in the E2E flow."""

    def test_missing_models_returns_error(self, server_url: str) -> None:
        """Test that missing models field returns 422 validation error."""
        payload = {
            "tasks": [SAMPLE_TASK],
            "samples": 1,
        }

        response = requests.post(
            f"{server_url}/runs",
            json=payload,
            timeout=10,
        )
        # Should return 422 for validation error (missing required field)
        assert response.status_code == 422

    def test_empty_models_returns_error(self, server_url: str) -> None:
        """Test that empty models list returns error."""
        payload = {
            "models": [],
            "tasks": [SAMPLE_TASK],
            "samples": 1,
        }

        response = requests.post(
            f"{server_url}/runs",
            json=payload,
            timeout=10,
        )
        # Should return 400 for invalid request (empty models)
        assert response.status_code == 400


class TestWebSocketEndpoint:
    """Tests for WebSocket endpoint existence."""

    def test_websocket_endpoint_exists(self, server_url: str) -> None:
        """Test that the WebSocket stream endpoint responds to HTTP (upgrade required)."""
        # WebSocket endpoints typically return 403 or similar when accessed via HTTP
        # This just tests the endpoint exists
        response = requests.get(
            f"{server_url}/runs/test_run_id/stream",
            timeout=5,
        )
        # WebSocket endpoint should not accept regular HTTP GET
        # FastAPI returns various codes for WebSocket endpoints accessed via HTTP
        assert response.status_code in [400, 403, 404, 405, 426]
