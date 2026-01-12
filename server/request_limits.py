"""Request limits middleware for the FastAPI server.

Provides:
- Request body size limits with 413 responses for oversized requests
- Optional rate limiting for mutating endpoints with 429 responses
"""

from __future__ import annotations

import os
import time
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


# Default maximum request body size: 10 MB
DEFAULT_MAX_BODY_SIZE = 10 * 1024 * 1024

# Default rate limit: 100 requests per minute per IP
DEFAULT_RATE_LIMIT = 100
DEFAULT_RATE_WINDOW_SECONDS = 60


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Middleware that enforces request body size limits.

    Returns HTTP 413 (Payload Too Large) for requests exceeding the limit.

    Args:
        app: The ASGI application.
        max_body_size: Maximum allowed request body size in bytes.
        exclude_paths: List of path prefixes to exclude from size limits.
    """

    def __init__(
        self,
        app: Any,
        max_body_size: int | None = None,
        exclude_paths: list[str] | None = None,
    ) -> None:
        super().__init__(app)
        # Allow configuration via environment variable
        env_max_size = os.environ.get("MAX_REQUEST_BODY_SIZE")
        if max_body_size is not None:
            self.max_body_size = max_body_size
        elif env_max_size:
            try:
                self.max_body_size = int(env_max_size)
            except ValueError:
                self.max_body_size = DEFAULT_MAX_BODY_SIZE
        else:
            self.max_body_size = DEFAULT_MAX_BODY_SIZE
        self.exclude_paths = exclude_paths or []

    async def dispatch(self, request: Request, call_next: Callable[[Request], Any]) -> Response:
        """Check request body size before processing."""
        path = request.url.path

        # Skip excluded paths
        for exclude_path in self.exclude_paths:
            if path.startswith(exclude_path):
                return await call_next(request)

        # Skip GET, HEAD, OPTIONS requests (no body expected)
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return await call_next(request)

        # Check Content-Length header first (efficient early rejection)
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                length = int(content_length)
                if length > self.max_body_size:
                    return JSONResponse(
                        status_code=413,
                        content={"detail": f"Request body too large. Maximum size is {self.max_body_size} bytes."},
                    )
            except ValueError:
                pass  # Invalid Content-Length, let the request proceed

        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Middleware that enforces rate limiting for mutating endpoints.

    Returns HTTP 429 (Too Many Requests) when rate limit is exceeded.
    Disabled by default for local development; enable via environment variable.

    Args:
        app: The ASGI application.
        rate_limit: Maximum requests per window.
        window_seconds: Time window in seconds.
        enabled: Whether rate limiting is enabled (default: check env var).
        mutating_only: Only limit POST/PUT/PATCH/DELETE requests.
        exclude_paths: List of path prefixes to exclude from rate limiting.
    """

    def __init__(
        self,
        app: Any,
        rate_limit: int | None = None,
        window_seconds: int | None = None,
        enabled: bool | None = None,
        mutating_only: bool = True,
        exclude_paths: list[str] | None = None,
    ) -> None:
        super().__init__(app)

        # Determine if rate limiting is enabled
        if enabled is not None:
            self.enabled = enabled
        else:
            # Off by default; enable via env var
            env_enabled = os.environ.get("ENABLE_RATE_LIMITING", "").lower()
            self.enabled = env_enabled in ("1", "true", "yes", "on")

        # Configure rate limit parameters
        env_rate_limit = os.environ.get("RATE_LIMIT")
        if rate_limit is not None:
            self.rate_limit = rate_limit
        elif env_rate_limit:
            try:
                self.rate_limit = int(env_rate_limit)
            except ValueError:
                self.rate_limit = DEFAULT_RATE_LIMIT
        else:
            self.rate_limit = DEFAULT_RATE_LIMIT

        env_window = os.environ.get("RATE_LIMIT_WINDOW_SECONDS")
        if window_seconds is not None:
            self.window_seconds = window_seconds
        elif env_window:
            try:
                self.window_seconds = int(env_window)
            except ValueError:
                self.window_seconds = DEFAULT_RATE_WINDOW_SECONDS
        else:
            self.window_seconds = DEFAULT_RATE_WINDOW_SECONDS

        self.mutating_only = mutating_only
        self.exclude_paths = exclude_paths or []

        # In-memory request tracking: IP -> list of timestamps
        self._requests: dict[str, list[float]] = defaultdict(list)

    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP from request, handling proxies."""
        # Check X-Forwarded-For header (set by reverse proxies)
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            # Take the first IP in the chain (original client)
            return forwarded_for.split(",")[0].strip()

        # Check X-Real-IP header (common alternative)
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip.strip()

        # Fall back to direct client IP
        if request.client:
            return request.client.host

        return "unknown"

    def _is_rate_limited(self, client_ip: str) -> tuple[bool, int, int]:
        """Check if client is rate limited.

        Returns:
            Tuple of (is_limited, remaining_requests, retry_after_seconds)
        """
        now = time.time()
        window_start = now - self.window_seconds

        # Clean up old entries and count recent requests
        recent_requests = [ts for ts in self._requests[client_ip] if ts > window_start]
        self._requests[client_ip] = recent_requests

        remaining = max(0, self.rate_limit - len(recent_requests))

        if len(recent_requests) >= self.rate_limit:
            # Calculate when the oldest request in window will expire
            if recent_requests:
                oldest = min(recent_requests)
                retry_after = max(1, int(oldest + self.window_seconds - now))
            else:
                retry_after = self.window_seconds
            return True, remaining, retry_after

        return False, remaining, 0

    def _record_request(self, client_ip: str) -> None:
        """Record a request for rate limiting purposes."""
        self._requests[client_ip].append(time.time())

    async def dispatch(self, request: Request, call_next: Callable[[Request], Any]) -> Response:
        """Check rate limit before processing request."""
        # Skip if rate limiting is disabled
        if not self.enabled:
            return await call_next(request)

        path = request.url.path

        # Skip excluded paths
        for exclude_path in self.exclude_paths:
            if path.startswith(exclude_path):
                return await call_next(request)

        # Skip non-mutating requests if configured
        mutating_methods = {"POST", "PUT", "PATCH", "DELETE"}
        if self.mutating_only and request.method not in mutating_methods:
            return await call_next(request)

        client_ip = self._get_client_ip(request)
        is_limited, remaining, retry_after = self._is_rate_limited(client_ip)

        if is_limited:
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Rate limit exceeded. Please try again later.",
                    "retry_after_seconds": retry_after,
                },
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(self.rate_limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(time.time()) + retry_after),
                },
            )

        # Record this request
        self._record_request(client_ip)

        # Process request and add rate limit headers to response
        response = await call_next(request)

        # Add rate limit headers to successful responses
        _, remaining_after, _ = self._is_rate_limited(client_ip)
        response.headers["X-RateLimit-Limit"] = str(self.rate_limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining_after)
        response.headers["X-RateLimit-Reset"] = str(int(time.time()) + self.window_seconds)

        return response


def get_request_size_limit_middleware(
    max_body_size: int | None = None,
    exclude_paths: list[str] | None = None,
) -> type[RequestSizeLimitMiddleware]:
    """Factory function to create a configured RequestSizeLimitMiddleware class.

    Args:
        max_body_size: Maximum request body size in bytes.
        exclude_paths: Paths to exclude from size limits.

    Returns:
        A configured middleware class.
    """

    class ConfiguredRequestSizeLimitMiddleware(RequestSizeLimitMiddleware):
        def __init__(self, app: Any) -> None:
            super().__init__(
                app,
                max_body_size=max_body_size,
                exclude_paths=exclude_paths,
            )

    return ConfiguredRequestSizeLimitMiddleware


def get_rate_limit_middleware(
    rate_limit: int | None = None,
    window_seconds: int | None = None,
    enabled: bool | None = None,
    mutating_only: bool = True,
    exclude_paths: list[str] | None = None,
) -> type[RateLimitMiddleware]:
    """Factory function to create a configured RateLimitMiddleware class.

    Args:
        rate_limit: Maximum requests per window.
        window_seconds: Time window in seconds.
        enabled: Whether rate limiting is enabled.
        mutating_only: Only limit mutating requests.
        exclude_paths: Paths to exclude from rate limiting.

    Returns:
        A configured middleware class.
    """

    class ConfiguredRateLimitMiddleware(RateLimitMiddleware):
        def __init__(self, app: Any) -> None:
            super().__init__(
                app,
                rate_limit=rate_limit,
                window_seconds=window_seconds,
                enabled=enabled,
                mutating_only=mutating_only,
                exclude_paths=exclude_paths,
            )

    return ConfiguredRateLimitMiddleware
