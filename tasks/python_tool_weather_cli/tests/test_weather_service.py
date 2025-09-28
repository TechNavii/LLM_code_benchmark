import json
import os
import subprocess
from pathlib import Path

import pytest

import weather_service

TOOL_PATH = Path(__file__).resolve().parents[1] / "workspace" / "tools" / "weather_tool.py"
TOKEN_FILE = TOOL_PATH.with_name('.last_call')


@pytest.fixture(autouse=True)
def cleanup_token_file():
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()
    yield
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()


def test_successful_tool_call(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).resolve().parents[1] / "workspace"))

    result = weather_service.get_weather("Osaka")
    assert result["city"] == "Osaka"
    assert "token" in result
    assert Path(TOKEN_FILE).exists()
    assert TOKEN_FILE.read_text(encoding="utf-8") == result["token"]


def test_missing_city_raises_error():
    with pytest.raises(RuntimeError):
        weather_service.get_weather(" ")


def test_tool_failure_propagates(monkeypatch):
    """When tool fails, service should raise informative error."""

    # Simulate tool failure by temporarily renaming script
    temp_path = TOOL_PATH.with_suffix(".temp")
    TOOL_PATH.rename(temp_path)
    try:
        with pytest.raises(RuntimeError):
            weather_service.get_weather("Tokyo")
    finally:
        temp_path.rename(TOOL_PATH)


def test_json_parsing_failure(monkeypatch):
    """If tool prints invalid JSON, the service should raise an error."""

    wrapper = TOOL_PATH.with_name('weather_tool_invalid.py')
    wrapper.write_text(
        "#!/usr/bin/env python3\nprint('not json')\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)

    try:
        monkeypatch.setattr(weather_service, "_TOOL_PATH", wrapper)
        with pytest.raises(RuntimeError):
            weather_service.get_weather("Berlin")
    finally:
        if wrapper.exists():
            wrapper.unlink()
