"""Structured logging setup utilities."""

from __future__ import annotations

import logging
from collections.abc import Iterable

import structlog

from server.redaction import redact_secrets


def configure_logging(handlers: Iterable[logging.Handler] | None = None) -> None:
    """Configure stdlib logging and structlog with JSON output.

    Includes automatic redaction of sensitive data (API keys, Bearer tokens,
    and other common secret patterns) to prevent accidental credential leakage.
    """

    if handlers is None:
        handlers = [logging.StreamHandler()]

    logging.basicConfig(
        level=logging.INFO,
        handlers=list(handlers),
        format="%(message)s",
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            # Redact secrets before final rendering
            redact_secrets,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
