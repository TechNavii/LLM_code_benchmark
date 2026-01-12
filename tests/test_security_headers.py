"""Tests for HTTP security headers middleware.

Verifies that security headers are properly set on responses to protect against
common web vulnerabilities.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api import create_app
from server.security_headers import (
    DEFAULT_CSP,
    DEFAULT_SECURITY_HEADERS,
    SecurityHeadersMiddleware,
)


@pytest.fixture
def client() -> TestClient:
    """Create a test client for the FastAPI app."""
    app = create_app()
    return TestClient(app)


class TestSecurityHeadersOnHealth:
    """Test security headers on /health endpoint (JSON API)."""

    def test_x_content_type_options_present(self, client: TestClient) -> None:
        """Test X-Content-Type-Options header is set."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.headers.get("x-content-type-options") == "nosniff"

    def test_referrer_policy_present(self, client: TestClient) -> None:
        """Test Referrer-Policy header is set."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.headers.get("referrer-policy") == "strict-origin-when-cross-origin"

    def test_permissions_policy_present(self, client: TestClient) -> None:
        """Test Permissions-Policy header is set."""
        response = client.get("/health")
        assert response.status_code == 200
        permissions = response.headers.get("permissions-policy")
        assert permissions is not None
        assert "accelerometer=()" in permissions
        assert "camera=()" in permissions
        assert "microphone=()" in permissions

    def test_x_xss_protection_present(self, client: TestClient) -> None:
        """Test X-XSS-Protection header is set."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.headers.get("x-xss-protection") == "1; mode=block"

    def test_csp_not_on_json_api(self, client: TestClient) -> None:
        """Test CSP is not set on JSON API responses (only UI)."""
        response = client.get("/health")
        assert response.status_code == 200
        # CSP should not be present on pure API endpoints
        assert response.headers.get("content-security-policy") is None

    def test_x_frame_options_not_on_json_api(self, client: TestClient) -> None:
        """Test X-Frame-Options is not set on JSON API responses."""
        response = client.get("/health")
        assert response.status_code == 200
        # X-Frame-Options should not be present on pure API endpoints
        assert response.headers.get("x-frame-options") is None


class TestSecurityHeadersOnUI:
    """Test security headers on UI routes (HTML)."""

    def test_csp_on_ui_route(self, client: TestClient) -> None:
        """Test CSP is set on UI routes."""
        response = client.get("/ui/index.html")
        # May be 200 or 404 depending on whether file exists
        if response.status_code == 200:
            csp = response.headers.get("content-security-policy")
            assert csp is not None
            assert "default-src 'self'" in csp

    def test_x_frame_options_on_ui_route(self, client: TestClient) -> None:
        """Test X-Frame-Options is set on UI routes."""
        response = client.get("/ui/index.html")
        if response.status_code == 200:
            assert response.headers.get("x-frame-options") == "SAMEORIGIN"

    def test_all_security_headers_on_ui(self, client: TestClient) -> None:
        """Test all security headers are present on UI routes."""
        response = client.get("/ui/index.html")
        if response.status_code == 200:
            assert response.headers.get("x-content-type-options") == "nosniff"
            assert response.headers.get("referrer-policy") == "strict-origin-when-cross-origin"
            assert response.headers.get("x-xss-protection") == "1; mode=block"
            assert response.headers.get("permissions-policy") is not None


class TestSecurityHeadersOnQAUI:
    """Test security headers on QA UI routes."""

    def test_security_headers_on_qa_ui(self, client: TestClient) -> None:
        """Test security headers are present on QA UI routes."""
        # The /qa/ui path should also get security headers
        response = client.get("/ui/qa/index.html")
        if response.status_code == 200:
            assert response.headers.get("x-content-type-options") == "nosniff"
            assert response.headers.get("referrer-policy") is not None


class TestSecurityHeadersOnAPIEndpoints:
    """Test security headers on various API endpoints."""

    def test_headers_on_runs_list(self, client: TestClient) -> None:
        """Test security headers on /runs endpoint."""
        response = client.get("/runs")
        assert response.status_code == 200
        assert response.headers.get("x-content-type-options") == "nosniff"
        assert response.headers.get("referrer-policy") is not None

    def test_headers_on_leaderboard(self, client: TestClient) -> None:
        """Test security headers on /leaderboard endpoint."""
        response = client.get("/leaderboard")
        assert response.status_code == 200
        assert response.headers.get("x-content-type-options") == "nosniff"
        assert response.headers.get("referrer-policy") is not None

    def test_headers_on_qa_runs(self, client: TestClient) -> None:
        """Test security headers on /qa/runs endpoint."""
        response = client.get("/qa/runs")
        assert response.status_code == 200
        assert response.headers.get("x-content-type-options") == "nosniff"
        assert response.headers.get("referrer-policy") is not None

    def test_headers_on_qa_leaderboard(self, client: TestClient) -> None:
        """Test security headers on /qa/leaderboard endpoint."""
        response = client.get("/qa/leaderboard")
        assert response.status_code == 200
        assert response.headers.get("x-content-type-options") == "nosniff"
        assert response.headers.get("referrer-policy") is not None


class TestSecurityHeadersMiddlewareUnit:
    """Unit tests for SecurityHeadersMiddleware class."""

    def test_default_headers_match_constants(self) -> None:
        """Test DEFAULT_SECURITY_HEADERS contains expected headers."""
        assert "X-Content-Type-Options" in DEFAULT_SECURITY_HEADERS
        assert "Referrer-Policy" in DEFAULT_SECURITY_HEADERS
        assert "Permissions-Policy" in DEFAULT_SECURITY_HEADERS
        assert "X-Frame-Options" in DEFAULT_SECURITY_HEADERS
        assert "X-XSS-Protection" in DEFAULT_SECURITY_HEADERS
        assert "Content-Security-Policy" in DEFAULT_SECURITY_HEADERS

    def test_default_csp_is_defined(self) -> None:
        """Test DEFAULT_CSP contains key directives."""
        assert "default-src 'self'" in DEFAULT_CSP
        assert "script-src" in DEFAULT_CSP
        assert "style-src" in DEFAULT_CSP
        assert "frame-ancestors 'self'" in DEFAULT_CSP

    def test_custom_headers_override(self) -> None:
        """Test custom headers override defaults."""
        app = FastAPI()

        @app.get("/test")
        def test_endpoint() -> dict[str, str]:
            return {"test": "ok"}

        app.add_middleware(
            SecurityHeadersMiddleware,
            headers={"X-Custom-Header": "custom-value"},
        )

        client = TestClient(app)
        response = client.get("/test")
        assert response.headers.get("x-custom-header") == "custom-value"
        # Default headers should still be present
        assert response.headers.get("x-content-type-options") == "nosniff"

    def test_custom_csp_override(self) -> None:
        """Test custom CSP overrides default on UI paths."""
        app = FastAPI()

        # Create endpoint on a /ui path to get CSP applied
        @app.get("/ui/test")
        def test_endpoint() -> dict[str, str]:
            return {"test": "ok"}

        app.add_middleware(
            SecurityHeadersMiddleware,
            csp="default-src 'none'",
        )

        client = TestClient(app)
        response = client.get("/ui/test")
        # UI paths always get CSP regardless of content-type
        assert response.headers.get("content-security-policy") == "default-src 'none'"

    def test_exclude_paths(self) -> None:
        """Test paths can be excluded from security headers."""
        app = FastAPI()

        @app.get("/test")
        def test_endpoint() -> dict[str, str]:
            return {"test": "ok"}

        @app.get("/excluded/test")
        def excluded_endpoint() -> dict[str, str]:
            return {"excluded": "ok"}

        app.add_middleware(
            SecurityHeadersMiddleware,
            exclude_paths=["/excluded"],
        )

        client = TestClient(app)

        # Regular path should have headers
        response = client.get("/test")
        assert response.headers.get("x-content-type-options") == "nosniff"

        # Excluded path should not have headers
        response = client.get("/excluded/test")
        assert response.headers.get("x-content-type-options") is None


class TestSecurityHeadersConsistency:
    """Test consistency of security headers across routes."""

    def test_headers_consistent_across_code_and_qa_routers(self, client: TestClient) -> None:
        """Test that code and QA routers have consistent security headers."""
        code_response = client.get("/runs")
        qa_response = client.get("/qa/runs")

        assert code_response.status_code == 200
        assert qa_response.status_code == 200

        # Both should have same security headers
        assert code_response.headers.get("x-content-type-options") == qa_response.headers.get("x-content-type-options")
        assert code_response.headers.get("referrer-policy") == qa_response.headers.get("referrer-policy")
        assert code_response.headers.get("permissions-policy") == qa_response.headers.get("permissions-policy")

    def test_headers_on_error_responses(self, client: TestClient) -> None:
        """Test security headers are present even on error responses."""
        response = client.get("/runs/nonexistent-run-id")
        assert response.status_code == 404
        # Security headers should still be present
        assert response.headers.get("x-content-type-options") == "nosniff"
        assert response.headers.get("referrer-policy") is not None

    def test_headers_on_redirect_responses(self, client: TestClient) -> None:
        """Test security headers are present on redirect responses."""
        response = client.get("/", follow_redirects=False)
        assert response.status_code == 307
        # Security headers should still be present
        assert response.headers.get("x-content-type-options") == "nosniff"


class TestCSPDirectives:
    """Test Content Security Policy directive values."""

    def test_csp_allows_self_origin(self) -> None:
        """Test CSP allows resources from same origin."""
        assert "'self'" in DEFAULT_CSP

    def test_csp_allows_inline_scripts_for_gui(self) -> None:
        """Test CSP allows unsafe-inline for scripts (needed for GUI)."""
        assert "'unsafe-inline'" in DEFAULT_CSP

    def test_csp_allows_websocket_connections(self) -> None:
        """Test CSP allows WebSocket connections."""
        assert "connect-src" in DEFAULT_CSP
        assert "ws:" in DEFAULT_CSP
        assert "wss:" in DEFAULT_CSP

    def test_csp_prevents_clickjacking(self) -> None:
        """Test CSP frame-ancestors prevents clickjacking."""
        assert "frame-ancestors 'self'" in DEFAULT_CSP

    def test_csp_restricts_form_action(self) -> None:
        """Test CSP restricts form submissions."""
        assert "form-action 'self'" in DEFAULT_CSP

    def test_csp_restricts_base_uri(self) -> None:
        """Test CSP restricts base element."""
        assert "base-uri 'self'" in DEFAULT_CSP

    def test_csp_allows_data_uris_for_images(self) -> None:
        """Test CSP allows data URIs for images."""
        assert "img-src" in DEFAULT_CSP
        assert "data:" in DEFAULT_CSP
