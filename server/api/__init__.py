"""FastAPI application entrypoint."""

from server.api import app  # noqa: F401

__all__ = ["app"]