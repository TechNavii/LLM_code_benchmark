"""HTTP security headers middleware for the FastAPI server.

Provides standard security headers to protect against common web vulnerabilities.
"""

from __future__ import annotations

from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


# Default Content Security Policy for the UI
# - self: scripts/styles from same origin
# - unsafe-inline for style: needed for inline styles in the GUI
# - unsafe-eval: needed for some GUI JavaScript functionality
# - connect-src: allow WebSocket and API connections
# - img-src: allow data URIs for embedded images
DEFAULT_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "font-src 'self' data:; "
    "connect-src 'self' ws: wss:; "
    "frame-ancestors 'self'; "
    "form-action 'self'; "
    "base-uri 'self'"
)

# Default security headers
DEFAULT_SECURITY_HEADERS: dict[str, str] = {
    # Prevent MIME type sniffing
    "X-Content-Type-Options": "nosniff",
    # Control referrer information
    "Referrer-Policy": "strict-origin-when-cross-origin",
    # Disable browser features not needed
    "Permissions-Policy": (
        "accelerometer=(), "
        "camera=(), "
        "geolocation=(), "
        "gyroscope=(), "
        "magnetometer=(), "
        "microphone=(), "
        "payment=(), "
        "usb=()"
    ),
    # Prevent clickjacking
    "X-Frame-Options": "SAMEORIGIN",
    # XSS protection (legacy, but still useful for older browsers)
    "X-XSS-Protection": "1; mode=block",
    # Content Security Policy
    "Content-Security-Policy": DEFAULT_CSP,
}

# Headers to add only to HTML responses (UI routes)
HTML_ONLY_HEADERS = {"Content-Security-Policy", "X-Frame-Options"}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware that adds security headers to HTTP responses.

    Args:
        app: The ASGI application.
        headers: Custom security headers to use (overrides defaults).
        csp: Custom Content Security Policy (overrides default CSP).
        exclude_paths: List of path prefixes to exclude from security headers.
    """

    def __init__(
        self,
        app: Any,
        headers: dict[str, str] | None = None,
        csp: str | None = None,
        exclude_paths: list[str] | None = None,
    ) -> None:
        super().__init__(app)
        self.headers = dict(DEFAULT_SECURITY_HEADERS)
        if headers:
            self.headers.update(headers)
        if csp:
            self.headers["Content-Security-Policy"] = csp
        self.exclude_paths = exclude_paths or []

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        """Process request and add security headers to response."""
        response = await call_next(request)

        # Skip excluded paths
        path = request.url.path
        for exclude_path in self.exclude_paths:
            if path.startswith(exclude_path):
                return response

        # Determine if this is likely an HTML response (UI routes)
        content_type = response.headers.get("content-type", "")
        is_html = "text/html" in content_type

        # Determine if this is a UI path
        is_ui_path = path.startswith("/ui") or path.startswith("/qa/ui")

        # Add security headers
        for header_name, header_value in self.headers.items():
            # Skip HTML-only headers for non-HTML API responses
            if header_name in HTML_ONLY_HEADERS and not (is_html or is_ui_path):
                continue
            # Don't override existing headers
            if header_name not in response.headers:
                response.headers[header_name] = header_value

        return response


def get_security_headers_middleware(
    csp: str | None = None,
    headers: dict[str, str] | None = None,
    exclude_paths: list[str] | None = None,
) -> type[SecurityHeadersMiddleware]:
    """Factory function to create a configured SecurityHeadersMiddleware class.

    This is useful for passing configuration to add_middleware().

    Args:
        csp: Custom Content Security Policy.
        headers: Custom security headers.
        exclude_paths: Paths to exclude from security headers.

    Returns:
        A configured middleware class.
    """

    class ConfiguredSecurityHeadersMiddleware(SecurityHeadersMiddleware):
        def __init__(self, app: Any) -> None:
            super().__init__(
                app,
                headers=headers,
                csp=csp,
                exclude_paths=exclude_paths,
            )

    return ConfiguredSecurityHeadersMiddleware
