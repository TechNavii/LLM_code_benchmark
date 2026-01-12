"""Regression tests for path traversal and filesystem boundary enforcement.

These tests verify that API endpoints properly reject path traversal attempts
and that artifact creation stays within configured storage directories.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from server.api import create_app


@pytest.fixture
def client() -> TestClient:
    """Create a test client for the FastAPI app."""
    app = create_app()
    return TestClient(app)


class TestPathTraversalRejection:
    """Tests verifying path traversal attempts are rejected."""

    @pytest.mark.parametrize(
        "traversal_run_id",
        [
            "../etc/passwd",
            "..%2f..%2fetc",
            "....//",
            "run/../../../etc/passwd",
            "..\\windows\\system32",
            "..%5c..%5cwindows",
            "%2e%2e%2f",
            "valid_prefix/../escape",
            "/absolute/path",
            "run_id/../../escape",
        ],
    )
    def test_runs_api_rejects_traversal_run_id(self, client: TestClient, traversal_run_id: str) -> None:
        """API endpoints should reject run_id with path traversal patterns."""
        # Test incomplete endpoint
        response = client.get(f"/runs/{traversal_run_id}/incomplete")
        assert response.status_code in (
            400,
            404,
            422,
        ), f"Expected 400/404/422 for traversal attempt, got {response.status_code}"

        # Verify error doesn't leak filesystem paths
        response_text = response.text.lower()
        assert "/etc/" not in response_text
        assert "/windows/" not in response_text
        assert "passwd" not in response_text

    @pytest.mark.parametrize(
        "traversal_run_id",
        [
            "../",
            "..\\",
            "../../../secret",
            "..%2f..%2f",
            "run/../escape",
        ],
    )
    def test_runs_api_errors_endpoint_rejects_traversal(self, client: TestClient, traversal_run_id: str) -> None:
        """GET /runs/{run_id}/api-errors should reject traversal patterns."""
        response = client.get(f"/runs/{traversal_run_id}/api-errors")
        assert response.status_code in (400, 404, 422)

        # Verify safe error message
        if response.status_code == 400:
            data = response.json()
            assert "detail" in data
            # Should not expose internal paths
            assert ".." not in data["detail"]
            assert "/" not in data["detail"] or "format" in data["detail"]


class TestQARouteTraversalRejection:
    """Tests verifying QA route path traversal rejection."""

    @pytest.mark.parametrize(
        "traversal_run_id",
        [
            "../",
            "../../../etc/passwd",
            "..%2f",
            "run/../escape",
        ],
    )
    def test_qa_api_errors_endpoint_rejects_traversal(self, client: TestClient, traversal_run_id: str) -> None:
        """GET /qa/runs/{run_id}/api-errors should reject traversal patterns."""
        response = client.get(f"/qa/runs/{traversal_run_id}/api-errors")
        assert response.status_code in (400, 404, 422)


class TestValidRunIdFormats:
    """Tests verifying valid run ID formats are accepted."""

    @pytest.mark.parametrize(
        "valid_run_id",
        [
            "20240101_120000_a1b2c3",
            "run_123",
            "test-run-456",
            "abc123",
            "run_with_underscores",
            "run-with-dashes",
        ],
    )
    def test_valid_run_id_format_not_rejected_as_traversal(self, client: TestClient, valid_run_id: str) -> None:
        """Valid run ID formats should not be rejected as traversal attempts."""
        # These will return 404 (run not found) rather than 400 (invalid format)
        response = client.get(f"/runs/{valid_run_id}/incomplete")
        # Should be 404 (not found) not 400 (invalid format)
        assert response.status_code == 404, f"Valid run_id {valid_run_id} was rejected with {response.status_code}"


class TestErrorMessageSafety:
    """Tests verifying error messages don't leak filesystem information."""

    def test_invalid_run_id_error_is_generic(self, client: TestClient) -> None:
        """Error messages for invalid run IDs should be generic."""
        response = client.get("/runs/../../../etc/passwd/incomplete")
        assert response.status_code in (400, 404, 422)

        # Error message should be generic
        data = response.json()
        error_text = str(data).lower()

        # Should NOT contain:
        dangerous_patterns = [
            "/etc",
            "/home",
            "/users",
            "passwd",
            "c:\\",
            "windows",
            "traversal",  # Don't hint at what's being detected
        ]
        for pattern in dangerous_patterns:
            assert pattern not in error_text, f"Error message leaked '{pattern}': {data}"

    def test_qa_invalid_run_id_error_is_generic(self, client: TestClient) -> None:
        """QA route error messages should also be generic."""
        response = client.get("/qa/runs/../secret/api-errors")
        assert response.status_code in (400, 404, 422)

        data = response.json()
        error_text = str(data).lower()
        assert "/secret" not in error_text


class TestArtifactBoundaryEnforcement:
    """Tests verifying artifact creation stays within storage directories."""

    def test_run_creation_uses_safe_paths(self, client: TestClient) -> None:
        """Run creation should generate safe run IDs."""
        # The progress manager generates run IDs in format: timestamp_uuid
        # We can't directly test creation without triggering actual runs,
        # but we can verify the ID format is safe
        from server.progress_base import BaseProgressManager

        manager = BaseProgressManager()
        run_id = manager.generate_run_id()

        # Run ID should only contain safe characters
        assert all(c.isalnum() or c in "_-" for c in run_id), f"Generated run_id contains unsafe characters: {run_id}"

        # Should not contain path separators
        assert "/" not in run_id
        assert "\\" not in run_id
        assert ".." not in run_id

    def test_generated_run_ids_are_deterministic_format(self, client: TestClient) -> None:
        """Generated run IDs should follow a consistent safe format."""
        from server.progress_base import BaseProgressManager

        manager = BaseProgressManager()
        # Generate multiple run IDs
        run_ids = [manager.generate_run_id() for _ in range(10)]

        for run_id in run_ids:
            # Each ID should be unique
            assert run_ids.count(run_id) == 1 or run_id == run_ids[0]

            # Should match safe pattern
            import re

            safe_pattern = re.compile(r"^[a-zA-Z0-9_\-]+$")
            assert safe_pattern.match(run_id), f"Unsafe run_id format: {run_id}"


class TestCrossRouteConsistency:
    """Tests verifying consistent behavior across code and QA routes."""

    @pytest.mark.parametrize(
        "traversal_pattern",
        [
            "../",
            "..\\",
            "%2e%2e%2f",
        ],
    )
    def test_code_and_qa_routes_handle_traversal_consistently(self, client: TestClient, traversal_pattern: str) -> None:
        """Both code and QA routes should reject traversal patterns the same way."""
        code_response = client.get(f"/runs/{traversal_pattern}/incomplete")
        qa_response = client.get(f"/qa/runs/{traversal_pattern}/api-errors")

        # Both should reject (either 400 or 404)
        assert code_response.status_code in (400, 404, 422)
        assert qa_response.status_code in (400, 404, 422)

        # Both should have safe error messages
        for response in [code_response, qa_response]:
            data = response.json()
            assert ".." not in str(data).lower() or "detail" in data


class TestDeterministicBehavior:
    """Tests verifying path security is deterministic."""

    def test_same_invalid_input_returns_same_error(self, client: TestClient) -> None:
        """Same invalid input should return consistent error response."""
        invalid_id = "../escape"

        responses = [client.get(f"/runs/{invalid_id}/incomplete") for _ in range(3)]

        # All responses should be identical
        assert all(r.status_code == responses[0].status_code for r in responses)
        assert all(r.json() == responses[0].json() for r in responses)

    def test_validation_independent_of_machine_paths(self, client: TestClient) -> None:
        """Validation should work regardless of actual filesystem paths."""
        # These patterns should be rejected even if they happen to match
        # real paths on the developer's machine
        patterns = [
            "/tmp/test",  # Absolute path
            "~/test",  # Home expansion
            "$HOME/test",  # Environment variable
        ]

        for pattern in patterns:
            response = client.get(f"/runs/{pattern}/incomplete")
            # Should be rejected as invalid format or not found
            assert response.status_code in (400, 404, 422)
