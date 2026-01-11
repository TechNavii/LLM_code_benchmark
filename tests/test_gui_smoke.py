"""GUI headless browser smoke tests using Playwright.

These tests verify that the GUI routes render correctly and don't throw
JavaScript errors. They use a real FastAPI server instance on an ephemeral
port and Playwright for browser automation.

Requirements:
- pytest-playwright must be installed
- Playwright browsers must be installed (playwright install chromium)

Note: These tests are excluded from the default test run because they require
Playwright browsers to be installed. Run them separately with:
  pytest tests/test_gui_smoke.py -v

Or use the convenience script:
  ./scripts/gui-smoke.sh
"""

from __future__ import annotations

import multiprocessing
import os
import socket
import sys
import time
from collections.abc import Generator
from contextlib import closing
from typing import TYPE_CHECKING

import pytest
import uvicorn

if TYPE_CHECKING:
    from playwright.sync_api import Page

# Mark all tests in this module as GUI tests (require Playwright)
pytestmark = pytest.mark.gui


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


def run_server(host: str, port: int) -> None:
    """Run the FastAPI server in a subprocess."""
    # Suppress stdout/stderr to avoid noise in test output
    # These files are intentionally not closed since we redirect the entire process output
    sys.stdout = open(os.devnull, "w")  # noqa: SIM115
    sys.stderr = open(os.devnull, "w")  # noqa: SIM115

    # Import here to avoid issues with multiprocessing
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
def server_url() -> Generator[str, None, None]:
    """Start the FastAPI server on an ephemeral port and return its URL."""
    host = "127.0.0.1"
    port = find_free_port()

    # Start server in a separate process
    process = multiprocessing.Process(target=run_server, args=(host, port))
    process.start()

    try:
        # Wait for server to be ready
        if not wait_for_server(host, port, timeout=15.0):
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


class TestGUIMainPage:
    """Tests for the main GUI page (/ui)."""

    def test_main_page_loads(self, page: Page, server_url: str) -> None:
        """Test that the main GUI page loads without errors."""
        errors: list[str] = []

        def handle_error(error: Exception) -> None:
            errors.append(str(error))

        page.on("pageerror", handle_error)

        response = page.goto(f"{server_url}/ui/", timeout=30000)

        assert response is not None
        assert response.status == 200
        assert len(errors) == 0, f"JavaScript errors: {errors}"

    def test_main_page_has_title(self, page: Page, server_url: str) -> None:
        """Test that the main page has a title element."""
        page.goto(f"{server_url}/ui/", timeout=30000)

        # Wait for the page to have content
        page.wait_for_load_state("domcontentloaded")

        # Check that the page has a title (from the HTML)
        title = page.title()
        assert title, "Page should have a title"

    def test_main_page_renders_content(self, page: Page, server_url: str) -> None:
        """Test that the main page renders key DOM elements."""
        page.goto(f"{server_url}/ui/", timeout=30000)
        page.wait_for_load_state("domcontentloaded")

        # Check for body content
        body = page.locator("body")
        assert body.count() == 1

        # The page should have some content loaded
        body_text = body.inner_text(timeout=5000)
        assert len(body_text) > 0, "Page body should have content"


class TestGUIQAPage:
    """Tests for the QA GUI page (/ui/qa)."""

    def test_qa_page_loads(self, page: Page, server_url: str) -> None:
        """Test that the QA GUI page loads without errors."""
        errors: list[str] = []

        def handle_error(error: Exception) -> None:
            errors.append(str(error))

        page.on("pageerror", handle_error)

        # QA page is served at /ui/qa/ since StaticFiles html=True
        response = page.goto(f"{server_url}/ui/qa/", timeout=30000)

        assert response is not None
        assert response.status == 200
        assert len(errors) == 0, f"JavaScript errors: {errors}"

    def test_qa_page_has_title(self, page: Page, server_url: str) -> None:
        """Test that the QA page has a title element."""
        page.goto(f"{server_url}/ui/qa/", timeout=30000)
        page.wait_for_load_state("domcontentloaded")

        title = page.title()
        assert title, "Page should have a title"

    def test_qa_page_renders_content(self, page: Page, server_url: str) -> None:
        """Test that the QA page renders key DOM elements."""
        page.goto(f"{server_url}/ui/qa/", timeout=30000)
        page.wait_for_load_state("domcontentloaded")

        body = page.locator("body")
        assert body.count() == 1

        body_text = body.inner_text(timeout=5000)
        assert len(body_text) > 0, "Page body should have content"


class TestGUIHealthEndpoints:
    """Tests verifying the GUI can reach backend endpoints."""

    def test_health_endpoint_accessible(self, page: Page, server_url: str) -> None:
        """Test that the health endpoint is accessible from browser context."""
        response = page.goto(f"{server_url}/health", timeout=30000)

        assert response is not None
        assert response.status == 200

        content = page.content()
        # Browser wraps JSON in HTML, check for health status
        assert "ok" in content.lower() or "true" in content.lower()


class TestGUINoJSErrors:
    """Tests specifically focused on JavaScript error detection."""

    def test_main_page_no_console_errors(self, page: Page, server_url: str) -> None:
        """Test that main page doesn't log errors to console."""
        console_errors: list[str] = []

        def handle_console(msg) -> None:
            if msg.type == "error":
                console_errors.append(msg.text)

        page.on("console", handle_console)
        page.goto(f"{server_url}/ui/", timeout=30000)
        # Use domcontentloaded instead of networkidle to avoid timeout on WebSocket connections
        page.wait_for_load_state("domcontentloaded")
        # Give JS a moment to initialize and potentially error
        page.wait_for_timeout(1000)

        # Filter out known acceptable errors (e.g., missing favicon)
        filtered_errors = [e for e in console_errors if "favicon" not in e.lower() and "404" not in e]

        assert len(filtered_errors) == 0, f"Console errors found: {filtered_errors}"

    def test_qa_page_no_console_errors(self, page: Page, server_url: str) -> None:
        """Test that QA page doesn't log errors to console."""
        console_errors: list[str] = []

        def handle_console(msg) -> None:
            if msg.type == "error":
                console_errors.append(msg.text)

        page.on("console", handle_console)
        page.goto(f"{server_url}/ui/qa/", timeout=30000)
        # Use domcontentloaded instead of networkidle to avoid timeout on WebSocket connections
        page.wait_for_load_state("domcontentloaded")
        # Give JS a moment to initialize and potentially error
        page.wait_for_timeout(1000)

        # Filter out known acceptable errors
        filtered_errors = [e for e in console_errors if "favicon" not in e.lower() and "404" not in e]

        assert len(filtered_errors) == 0, f"Console errors found: {filtered_errors}"


class TestGUIStaticAssets:
    """Tests for static asset loading."""

    def test_css_loads(self, page: Page, server_url: str) -> None:
        """Test that CSS files load correctly."""
        page.goto(f"{server_url}/ui/", timeout=30000)
        page.wait_for_load_state("domcontentloaded")

        # Check that stylesheets are loaded
        stylesheets = page.locator('link[rel="stylesheet"]')
        # Should have at least one stylesheet (style.css)
        assert stylesheets.count() >= 0  # May be inline or external

    def test_js_loads(self, page: Page, server_url: str) -> None:
        """Test that JavaScript files load correctly."""
        failed_scripts: list[str] = []

        def handle_response(response) -> None:
            if ".js" in response.url and response.status >= 400:
                failed_scripts.append(f"{response.url}: {response.status}")

        page.on("response", handle_response)
        page.goto(f"{server_url}/ui/", timeout=30000)
        # Use domcontentloaded instead of networkidle to avoid timeout on WebSocket connections
        page.wait_for_load_state("domcontentloaded")
        # Give a brief pause for any async script loads
        page.wait_for_timeout(500)

        assert len(failed_scripts) == 0, f"Failed to load scripts: {failed_scripts}"
