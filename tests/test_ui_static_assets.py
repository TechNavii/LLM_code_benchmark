"""Tests verifying UI static assets referenced by HTML exist and are served.

These tests parse gui/index.html and gui/qa/index.html for referenced assets
and verify that each asset exists on disk and is served with a 200 response.
No Playwright required - uses FastAPI TestClient for HTTP verification.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.api import create_app

ROOT = Path(__file__).resolve().parents[1]
GUI_DIR = ROOT / "gui"


def extract_asset_references(html_path: Path) -> list[str]:
    """Extract /ui/* asset references from an HTML file.

    Returns list of paths like '/ui/style.css', '/ui/main.js', etc.
    Query strings (e.g., ?v=20260110_6) are stripped.
    """
    content = html_path.read_text()

    # Find src="..." and href="..." attributes
    pattern = r'(?:src|href)="(/ui/[^"?]+)'
    matches = re.findall(pattern, content)

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for path in matches:
        if path not in seen:
            seen.add(path)
            unique.append(path)

    return unique


def ui_path_to_disk_path(ui_path: str) -> Path:
    """Convert a /ui/* path to a disk path in gui/.

    Example: '/ui/style.css' -> gui/style.css
             '/ui/qa/main.js' -> gui/qa/main.js
    """
    if ui_path.startswith("/ui/"):
        relative = ui_path[4:]  # Remove '/ui/'
    else:
        relative = ui_path
    return GUI_DIR / relative


@pytest.fixture
def client() -> TestClient:
    """Create a test client for the FastAPI app."""
    app = create_app()
    return TestClient(app)


class TestAssetExtraction:
    """Tests for the asset extraction helper."""

    def test_extract_asset_references_finds_scripts(self) -> None:
        """Asset extraction finds script references."""
        assets = extract_asset_references(GUI_DIR / "index.html")
        script_assets = [a for a in assets if a.endswith(".js")]
        assert len(script_assets) > 0, "Expected at least one JS file reference"

    def test_extract_asset_references_finds_stylesheets(self) -> None:
        """Asset extraction finds stylesheet references."""
        assets = extract_asset_references(GUI_DIR / "index.html")
        css_assets = [a for a in assets if a.endswith(".css")]
        assert len(css_assets) > 0, "Expected at least one CSS file reference"

    def test_extract_asset_references_strips_query_strings(self) -> None:
        """Asset extraction strips query string parameters."""
        assets = extract_asset_references(GUI_DIR / "index.html")
        for asset in assets:
            assert "?" not in asset, f"Query string not stripped from {asset}"

    def test_extract_asset_references_deduplicates(self) -> None:
        """Asset extraction returns unique paths."""
        assets = extract_asset_references(GUI_DIR / "index.html")
        assert len(assets) == len(set(assets)), "Duplicate assets found"


class TestMainIndexAssets:
    """Tests for assets referenced in gui/index.html."""

    def test_main_index_assets_exist_on_disk(self) -> None:
        """All assets referenced in gui/index.html should exist on disk."""
        assets = extract_asset_references(GUI_DIR / "index.html")
        missing = []

        for asset in assets:
            # Skip navigation links (HTML files)
            if asset.endswith(".html"):
                continue
            disk_path = ui_path_to_disk_path(asset)
            if not disk_path.exists():
                missing.append(f"{asset} -> {disk_path}")

        assert not missing, f"Missing assets: {missing}"

    def test_main_index_assets_served_with_200(self, client: TestClient) -> None:
        """All assets referenced in gui/index.html should be served with 200."""
        assets = extract_asset_references(GUI_DIR / "index.html")
        failures = []

        for asset in assets:
            # Skip navigation links (HTML files)
            if asset.endswith(".html"):
                continue
            response = client.get(asset)
            if response.status_code != 200:
                failures.append(f"{asset}: {response.status_code}")

        assert not failures, f"Assets not served with 200: {failures}"

    def test_main_index_html_served(self, client: TestClient) -> None:
        """Main index.html should be served at /ui/."""
        response = client.get("/ui/")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")


class TestQAIndexAssets:
    """Tests for assets referenced in gui/qa/index.html."""

    def test_qa_index_assets_exist_on_disk(self) -> None:
        """All assets referenced in gui/qa/index.html should exist on disk."""
        qa_index = GUI_DIR / "qa" / "index.html"
        if not qa_index.exists():
            pytest.skip("gui/qa/index.html does not exist")

        assets = extract_asset_references(qa_index)
        missing = []

        for asset in assets:
            # Skip navigation links (HTML files)
            if asset.endswith(".html"):
                continue
            disk_path = ui_path_to_disk_path(asset)
            if not disk_path.exists():
                missing.append(f"{asset} -> {disk_path}")

        assert not missing, f"Missing assets: {missing}"

    def test_qa_index_assets_served_with_200(self, client: TestClient) -> None:
        """All assets referenced in gui/qa/index.html should be served with 200."""
        qa_index = GUI_DIR / "qa" / "index.html"
        if not qa_index.exists():
            pytest.skip("gui/qa/index.html does not exist")

        assets = extract_asset_references(qa_index)
        failures = []

        for asset in assets:
            # Skip navigation links (HTML files)
            if asset.endswith(".html"):
                continue
            response = client.get(asset)
            if response.status_code != 200:
                failures.append(f"{asset}: {response.status_code}")

        assert not failures, f"Assets not served with 200: {failures}"

    def test_qa_index_html_served(self, client: TestClient) -> None:
        """QA index.html should be served at /ui/qa/."""
        response = client.get("/ui/qa/")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")


class TestAssetContentTypes:
    """Tests verifying correct content types for assets."""

    def test_css_assets_have_correct_content_type(self, client: TestClient) -> None:
        """CSS files should be served with text/css content type."""
        assets = extract_asset_references(GUI_DIR / "index.html")
        css_assets = [a for a in assets if a.endswith(".css")]

        for asset in css_assets:
            response = client.get(asset)
            assert response.status_code == 200
            content_type = response.headers.get("content-type", "")
            assert "text/css" in content_type, f"{asset} has wrong content type: {content_type}"

    def test_js_assets_have_correct_content_type(self, client: TestClient) -> None:
        """JS files should be served with application/javascript content type."""
        assets = extract_asset_references(GUI_DIR / "index.html")
        js_assets = [a for a in assets if a.endswith(".js")]

        for asset in js_assets:
            response = client.get(asset)
            assert response.status_code == 200
            content_type = response.headers.get("content-type", "")
            # Accept both application/javascript and text/javascript
            assert "javascript" in content_type.lower(), f"{asset} has wrong content type: {content_type}"


class TestAssetConsistency:
    """Tests verifying consistent asset references across main and QA UIs."""

    def test_shared_assets_match(self) -> None:
        """Assets referenced by both main and QA should point to same files."""
        main_assets = set(extract_asset_references(GUI_DIR / "index.html"))
        qa_index = GUI_DIR / "qa" / "index.html"
        if not qa_index.exists():
            pytest.skip("gui/qa/index.html does not exist")

        qa_assets = set(extract_asset_references(qa_index))

        # Find shared assets (same path referenced by both)
        shared = main_assets & qa_assets

        # Shared assets should point to existing files
        for asset in shared:
            if asset.endswith(".html"):
                continue
            disk_path = ui_path_to_disk_path(asset)
            assert disk_path.exists(), f"Shared asset missing on disk: {asset}"

    def test_style_css_referenced_by_both(self) -> None:
        """style.css should be referenced by both main and QA UI."""
        main_assets = extract_asset_references(GUI_DIR / "index.html")
        qa_index = GUI_DIR / "qa" / "index.html"
        if not qa_index.exists():
            pytest.skip("gui/qa/index.html does not exist")

        qa_assets = extract_asset_references(qa_index)

        main_css = [a for a in main_assets if "style.css" in a]
        qa_css = [a for a in qa_assets if "style.css" in a]

        assert main_css, "Main index.html should reference style.css"
        assert qa_css, "QA index.html should reference style.css"
