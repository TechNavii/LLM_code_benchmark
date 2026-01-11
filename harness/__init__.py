"""Harness package exports."""

from harness.config import get_settings
from server.redaction import install_stdlib_redaction

# Install log redaction filter for harness loggers to prevent secret leakage
install_stdlib_redaction("harness")

__all__ = ["get_settings"]
