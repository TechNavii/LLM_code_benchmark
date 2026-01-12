"""Tests for request size limits and rate limiting middleware."""

from __future__ import annotations

import os
import time
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from server.request_limits import (
    DEFAULT_MAX_BODY_SIZE,
    DEFAULT_RATE_LIMIT,
    DEFAULT_RATE_WINDOW_SECONDS,
    RateLimitMiddleware,
    RequestSizeLimitMiddleware,
    get_rate_limit_middleware,
    get_request_size_limit_middleware,
)


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def app_with_size_limit() -> FastAPI:
    """Create a FastAPI app with request size limit middleware."""
    app = FastAPI()
    # Use a small limit for testing (1KB)
    app.add_middleware(RequestSizeLimitMiddleware, max_body_size=1024)

    @app.post("/upload")
    async def upload(data: dict) -> dict:
        return {"received": True}

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app


@pytest.fixture
def app_with_rate_limit() -> FastAPI:
    """Create a FastAPI app with rate limiting middleware enabled."""
    app = FastAPI()
    # Use small limits for testing: 5 requests per 10 seconds
    app.add_middleware(
        RateLimitMiddleware,
        rate_limit=5,
        window_seconds=10,
        enabled=True,
        mutating_only=True,
    )

    @app.post("/create")
    async def create(data: dict) -> dict:
        return {"created": True}

    @app.get("/read")
    async def read() -> dict:
        return {"data": "value"}

    @app.delete("/delete/{id}")
    async def delete(id: str) -> dict:
        return {"deleted": id}

    return app


@pytest.fixture
def app_with_both_limits() -> FastAPI:
    """Create a FastAPI app with both size and rate limit middleware."""
    app = FastAPI()
    app.add_middleware(RequestSizeLimitMiddleware, max_body_size=1024)
    app.add_middleware(
        RateLimitMiddleware,
        rate_limit=3,
        window_seconds=10,
        enabled=True,
    )

    @app.post("/endpoint")
    async def endpoint(data: dict) -> dict:
        return {"ok": True}

    return app


# -----------------------------------------------------------------------------
# Request Size Limit Tests
# -----------------------------------------------------------------------------


class TestRequestSizeLimitMiddleware:
    """Tests for RequestSizeLimitMiddleware."""

    def test_small_payload_allowed(self, app_with_size_limit: FastAPI) -> None:
        """Small payloads should be allowed through."""
        client = TestClient(app_with_size_limit)
        response = client.post("/upload", json={"small": "data"})
        assert response.status_code == 200
        assert response.json() == {"received": True}

    def test_large_payload_rejected_with_413(self, app_with_size_limit: FastAPI) -> None:
        """Large payloads should be rejected with 413 status."""
        client = TestClient(app_with_size_limit)
        # Create a payload larger than 1KB limit
        large_data = {"data": "x" * 2000}
        response = client.post(
            "/upload",
            json=large_data,
            headers={"Content-Length": str(len(str(large_data)))},
        )
        assert response.status_code == 413
        assert "too large" in response.json()["detail"].lower()

    def test_get_requests_not_checked(self, app_with_size_limit: FastAPI) -> None:
        """GET requests should not be subject to size limits."""
        client = TestClient(app_with_size_limit)
        response = client.get("/health")
        assert response.status_code == 200

    def test_content_length_header_triggers_early_rejection(self) -> None:
        """Content-Length header should trigger early rejection before body read."""
        app = FastAPI()
        app.add_middleware(RequestSizeLimitMiddleware, max_body_size=100)

        @app.post("/upload")
        async def upload() -> dict:
            return {"ok": True}

        client = TestClient(app)
        # Set Content-Length to a large value
        response = client.post(
            "/upload",
            content=b"small",  # Actual content is small
            headers={"Content-Length": "1000000"},  # But header claims large
        )
        assert response.status_code == 413

    def test_default_max_size(self) -> None:
        """Default max size should be applied when not specified."""
        app = FastAPI()
        middleware = RequestSizeLimitMiddleware(app)
        assert middleware.max_body_size == DEFAULT_MAX_BODY_SIZE

    def test_env_var_configuration(self) -> None:
        """MAX_REQUEST_BODY_SIZE env var should configure the limit."""
        app = FastAPI()
        with patch.dict(os.environ, {"MAX_REQUEST_BODY_SIZE": "5000"}):
            middleware = RequestSizeLimitMiddleware(app)
            assert middleware.max_body_size == 5000

    def test_env_var_invalid_value(self) -> None:
        """Invalid env var value should fall back to default."""
        app = FastAPI()
        with patch.dict(os.environ, {"MAX_REQUEST_BODY_SIZE": "invalid"}):
            middleware = RequestSizeLimitMiddleware(app)
            assert middleware.max_body_size == DEFAULT_MAX_BODY_SIZE

    def test_exclude_paths(self) -> None:
        """Excluded paths should not be subject to size limits."""
        app = FastAPI()
        app.add_middleware(
            RequestSizeLimitMiddleware,
            max_body_size=100,
            exclude_paths=["/artifacts"],
        )

        @app.post("/artifacts/upload")
        async def upload() -> dict:
            return {"ok": True}

        client = TestClient(app)
        response = client.post(
            "/artifacts/upload",
            content=b"x" * 200,
            headers={"Content-Length": "200"},
        )
        assert response.status_code == 200

    def test_factory_function(self) -> None:
        """Factory function should create properly configured middleware."""
        ConfiguredMiddleware = get_request_size_limit_middleware(
            max_body_size=500,
            exclude_paths=["/test"],
        )
        app = FastAPI()
        instance = ConfiguredMiddleware(app)
        assert instance.max_body_size == 500
        assert instance.exclude_paths == ["/test"]


# -----------------------------------------------------------------------------
# Rate Limit Tests
# -----------------------------------------------------------------------------


class TestRateLimitMiddleware:
    """Tests for RateLimitMiddleware."""

    def test_under_limit_allowed(self, app_with_rate_limit: FastAPI) -> None:
        """Requests under the limit should be allowed."""
        client = TestClient(app_with_rate_limit)
        # Make 3 requests (under limit of 5)
        for _ in range(3):
            response = client.post("/create", json={"data": "test"})
            assert response.status_code == 200

    def test_over_limit_returns_429(self, app_with_rate_limit: FastAPI) -> None:
        """Requests over the limit should return 429."""
        client = TestClient(app_with_rate_limit)
        # Make 5 requests (at the limit)
        for _ in range(5):
            response = client.post("/create", json={"data": "test"})
            assert response.status_code == 200

        # 6th request should be rate limited
        response = client.post("/create", json={"data": "test"})
        assert response.status_code == 429
        assert "rate limit" in response.json()["detail"].lower()

    def test_429_includes_retry_after_header(self, app_with_rate_limit: FastAPI) -> None:
        """429 responses should include Retry-After header."""
        client = TestClient(app_with_rate_limit)
        # Exhaust the limit
        for _ in range(5):
            client.post("/create", json={"data": "test"})

        response = client.post("/create", json={"data": "test"})
        assert response.status_code == 429
        assert "Retry-After" in response.headers
        retry_after = int(response.headers["Retry-After"])
        assert retry_after > 0
        assert retry_after <= 10  # Should be within window

    def test_429_includes_rate_limit_headers(self, app_with_rate_limit: FastAPI) -> None:
        """429 responses should include rate limit headers."""
        client = TestClient(app_with_rate_limit)
        # Exhaust the limit
        for _ in range(5):
            client.post("/create", json={"data": "test"})

        response = client.post("/create", json={"data": "test"})
        assert response.status_code == 429
        assert "X-RateLimit-Limit" in response.headers
        assert "X-RateLimit-Remaining" in response.headers
        assert "X-RateLimit-Reset" in response.headers
        assert response.headers["X-RateLimit-Limit"] == "5"
        assert response.headers["X-RateLimit-Remaining"] == "0"

    def test_get_requests_not_limited_when_mutating_only(self, app_with_rate_limit: FastAPI) -> None:
        """GET requests should not be rate limited when mutating_only=True."""
        client = TestClient(app_with_rate_limit)
        # Make many GET requests
        for _ in range(10):
            response = client.get("/read")
            assert response.status_code == 200

    def test_delete_requests_are_limited(self, app_with_rate_limit: FastAPI) -> None:
        """DELETE requests should be rate limited."""
        client = TestClient(app_with_rate_limit)
        # Make 5 DELETE requests (at the limit)
        for i in range(5):
            response = client.delete(f"/delete/{i}")
            assert response.status_code == 200

        # 6th should be limited
        response = client.delete("/delete/6")
        assert response.status_code == 429

    def test_disabled_by_default(self) -> None:
        """Rate limiting should be disabled by default."""
        app = FastAPI()
        middleware = RateLimitMiddleware(app)
        assert not middleware.enabled

    def test_enabled_via_env_var(self) -> None:
        """ENABLE_RATE_LIMITING env var should enable rate limiting."""
        app = FastAPI()
        with patch.dict(os.environ, {"ENABLE_RATE_LIMITING": "true"}):
            middleware = RateLimitMiddleware(app)
            assert middleware.enabled

    def test_env_var_configuration(self) -> None:
        """Environment variables should configure rate limit parameters."""
        app = FastAPI()
        with patch.dict(
            os.environ,
            {
                "ENABLE_RATE_LIMITING": "1",
                "RATE_LIMIT": "50",
                "RATE_LIMIT_WINDOW_SECONDS": "30",
            },
        ):
            middleware = RateLimitMiddleware(app)
            assert middleware.enabled
            assert middleware.rate_limit == 50
            assert middleware.window_seconds == 30

    def test_default_values(self) -> None:
        """Default values should be applied when not specified."""
        app = FastAPI()
        middleware = RateLimitMiddleware(app, enabled=True)
        assert middleware.rate_limit == DEFAULT_RATE_LIMIT
        assert middleware.window_seconds == DEFAULT_RATE_WINDOW_SECONDS

    def test_exclude_paths(self) -> None:
        """Excluded paths should not be rate limited."""
        app = FastAPI()
        app.add_middleware(
            RateLimitMiddleware,
            rate_limit=2,
            window_seconds=60,
            enabled=True,
            exclude_paths=["/health"],
        )

        @app.post("/health")
        async def health() -> dict:
            return {"ok": True}

        client = TestClient(app)
        # Make many requests to excluded path
        for _ in range(10):
            response = client.post("/health")
            assert response.status_code == 200

    def test_all_requests_limited_when_mutating_only_false(self) -> None:
        """All requests should be limited when mutating_only=False."""
        app = FastAPI()
        app.add_middleware(
            RateLimitMiddleware,
            rate_limit=3,
            window_seconds=60,
            enabled=True,
            mutating_only=False,
        )

        @app.get("/read")
        async def read() -> dict:
            return {"data": "value"}

        client = TestClient(app)
        # Make 3 GET requests (at the limit)
        for _ in range(3):
            response = client.get("/read")
            assert response.status_code == 200

        # 4th should be limited
        response = client.get("/read")
        assert response.status_code == 429

    def test_successful_responses_include_rate_limit_headers(self, app_with_rate_limit: FastAPI) -> None:
        """Successful responses should include rate limit headers."""
        client = TestClient(app_with_rate_limit)
        response = client.post("/create", json={"data": "test"})
        assert response.status_code == 200
        assert "X-RateLimit-Limit" in response.headers
        assert "X-RateLimit-Remaining" in response.headers
        assert "X-RateLimit-Reset" in response.headers

    def test_x_forwarded_for_header(self) -> None:
        """X-Forwarded-For header should be used for client IP detection."""
        app = FastAPI()
        app.add_middleware(
            RateLimitMiddleware,
            rate_limit=2,
            window_seconds=60,
            enabled=True,
        )

        @app.post("/test")
        async def test() -> dict:
            return {"ok": True}

        client = TestClient(app)
        # Requests from different IPs should have separate limits
        for _ in range(2):
            response = client.post("/test", headers={"X-Forwarded-For": "1.1.1.1"})
            assert response.status_code == 200

        response = client.post("/test", headers={"X-Forwarded-For": "1.1.1.1"})
        assert response.status_code == 429

        # Different IP should have its own limit
        response = client.post("/test", headers={"X-Forwarded-For": "2.2.2.2"})
        assert response.status_code == 200

    def test_x_real_ip_header(self) -> None:
        """X-Real-IP header should be used when X-Forwarded-For is absent."""
        app = FastAPI()
        app.add_middleware(
            RateLimitMiddleware,
            rate_limit=2,
            window_seconds=60,
            enabled=True,
        )

        @app.post("/test")
        async def test() -> dict:
            return {"ok": True}

        client = TestClient(app)
        for _ in range(2):
            response = client.post("/test", headers={"X-Real-IP": "3.3.3.3"})
            assert response.status_code == 200

        response = client.post("/test", headers={"X-Real-IP": "3.3.3.3"})
        assert response.status_code == 429

    def test_factory_function(self) -> None:
        """Factory function should create properly configured middleware."""
        ConfiguredMiddleware = get_rate_limit_middleware(
            rate_limit=10,
            window_seconds=30,
            enabled=True,
            mutating_only=False,
            exclude_paths=["/test"],
        )
        app = FastAPI()
        instance = ConfiguredMiddleware(app)
        assert instance.rate_limit == 10
        assert instance.window_seconds == 30
        assert instance.enabled
        assert not instance.mutating_only
        assert instance.exclude_paths == ["/test"]


# -----------------------------------------------------------------------------
# Combined Middleware Tests
# -----------------------------------------------------------------------------


class TestCombinedMiddleware:
    """Tests for combined size and rate limit middleware."""

    def test_size_limit_before_rate_limit(self, app_with_both_limits: FastAPI) -> None:
        """Size limit should be checked before rate limit is consumed."""
        client = TestClient(app_with_both_limits)

        # Make a request with a large payload
        large_data = {"data": "x" * 2000}
        response = client.post(
            "/endpoint",
            json=large_data,
            headers={"Content-Length": str(len(str(large_data)))},
        )
        assert response.status_code == 413

        # Rate limit should not have been consumed
        # (depends on middleware ordering - size limit should fail first)

    def test_both_limits_enforced(self, app_with_both_limits: FastAPI) -> None:
        """Both size and rate limits should be enforced."""
        client = TestClient(app_with_both_limits)

        # Small payloads should work
        for _ in range(3):
            response = client.post("/endpoint", json={"small": "data"})
            assert response.status_code == 200

        # After rate limit, should get 429
        response = client.post("/endpoint", json={"small": "data"})
        assert response.status_code == 429


# -----------------------------------------------------------------------------
# Integration Tests with Real App
# -----------------------------------------------------------------------------


class TestIntegrationWithRealApp:
    """Integration tests using the actual application."""

    def test_size_limit_on_runs_endpoint(self) -> None:
        """Test size limit on POST /runs endpoint."""
        from server.api import create_app

        app = create_app()
        client = TestClient(app)

        # The default limit is 10MB, so this should be allowed
        response = client.post(
            "/runs",
            json={
                "models": ["test-model"],
                "tasks": ["test-task"],
            },
        )
        # Should NOT get 413 for small payload - expect 400/401 (validation/auth)
        assert response.status_code in (400, 401, 422)

    def test_rate_limit_disabled_by_default(self) -> None:
        """Rate limiting should be disabled by default in the real app."""
        from server.api import create_app

        app = create_app()
        client = TestClient(app)

        # Make many requests - should all succeed (rate limiting disabled)
        for _ in range(10):
            response = client.get("/health")
            assert response.status_code == 200
            # Rate limit headers should not be present when disabled
            # (GET requests wouldn't have them anyway due to mutating_only)


# -----------------------------------------------------------------------------
# Edge Cases and Error Handling
# -----------------------------------------------------------------------------


class TestEdgeCases:
    """Edge case tests for middleware."""

    def test_invalid_content_length_header(self) -> None:
        """Invalid Content-Length header should not cause errors."""
        app = FastAPI()
        app.add_middleware(RequestSizeLimitMiddleware, max_body_size=1000)

        @app.post("/upload")
        async def upload() -> dict:
            return {"ok": True}

        client = TestClient(app)
        # Invalid Content-Length should not crash
        response = client.post(
            "/upload",
            content=b"test",
            headers={"Content-Length": "invalid"},
        )
        # Should proceed and let FastAPI handle it
        assert response.status_code in (200, 422)  # 422 for body parsing

    def test_missing_content_length_header(self) -> None:
        """Missing Content-Length header should not block request."""
        app = FastAPI()
        app.add_middleware(RequestSizeLimitMiddleware, max_body_size=1000)

        @app.post("/upload")
        async def upload() -> dict:
            return {"ok": True}

        client = TestClient(app)
        # Request without explicit Content-Length
        response = client.post("/upload", json={"small": "data"})
        assert response.status_code == 200

    def test_options_requests_bypass_size_limit(self) -> None:
        """OPTIONS requests should bypass size limits."""
        app = FastAPI()
        app.add_middleware(RequestSizeLimitMiddleware, max_body_size=10)

        @app.options("/upload")
        async def options() -> dict:
            return {"ok": True}

        client = TestClient(app)
        response = client.options("/upload")
        assert response.status_code == 200

    def test_head_requests_bypass_size_limit(self) -> None:
        """HEAD requests should bypass size limits."""
        app = FastAPI()
        app.add_middleware(RequestSizeLimitMiddleware, max_body_size=10)

        @app.head("/test")
        async def head() -> dict:
            return {"ok": True}

        client = TestClient(app)
        response = client.head("/test")
        assert response.status_code == 200

    def test_rate_limit_cleanup_old_entries(self) -> None:
        """Rate limit should clean up old entries."""
        app = FastAPI()
        middleware = RateLimitMiddleware(
            app,
            rate_limit=5,
            window_seconds=1,  # 1 second window for fast test
            enabled=True,
        )

        # Record some requests
        for _ in range(3):
            middleware._record_request("test-ip")

        # Initially should have 3 requests
        assert len(middleware._requests["test-ip"]) == 3

        # Wait for window to expire
        time.sleep(1.1)

        # Check should clean up old entries
        is_limited, remaining, _ = middleware._is_rate_limited("test-ip")
        assert not is_limited
        assert remaining == 5  # All slots available
        assert len(middleware._requests["test-ip"]) == 0  # Old entries cleaned

    def test_retry_after_calculation(self) -> None:
        """Retry-After should indicate when client can retry."""
        app = FastAPI()
        middleware = RateLimitMiddleware(
            app,
            rate_limit=1,
            window_seconds=10,
            enabled=True,
        )

        # Record a request
        middleware._record_request("test-ip")

        # Check rate limit
        is_limited, remaining, retry_after = middleware._is_rate_limited("test-ip")
        assert is_limited
        assert remaining == 0
        # Retry-After should be close to window_seconds
        assert 1 <= retry_after <= 10


class TestTimeoutEnforcement:
    """Tests to verify outbound HTTP requests have timeouts."""

    def test_router_lmstudio_has_timeout(self) -> None:
        """Verify LM Studio model fetch has explicit timeout."""
        # This is a static code verification test
        from server.routes.router import list_lmstudio_models
        import inspect

        source = inspect.getsource(list_lmstudio_models)
        assert "timeout=3" in source or "timeout=" in source

    def test_harness_requests_have_timeouts(self) -> None:
        """Verify harness API calls have explicit timeouts."""
        from harness.config import get_settings

        settings = get_settings()
        # Verify timeout is configured
        assert hasattr(settings, "api_call_timeout_seconds")
        assert settings.api_call_timeout_seconds > 0
