"""Centralized log redaction utilities to prevent secret/PII leakage.

This module provides redaction filters for:
- API keys (OpenRouter, OpenAI, Anthropic, etc.)
- Bearer tokens in Authorization headers
- Generic secret patterns (sk-*, key-*, token-*, etc.)
- Common PII patterns (emails in certain contexts)

Usage:
    Structlog: Add `redact_secrets` processor to the processor chain.
    Stdlib: Use `SecretRedactionFilter` as a logging filter.
"""

from __future__ import annotations

import logging
import re
from collections.abc import MutableMapping
from typing import Any


# Regex patterns for common secrets
# These are designed to be high-signal and avoid false-positive over-redaction
SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Bearer tokens in Authorization headers or strings
    (re.compile(r"Bearer\s+[A-Za-z0-9_\-./+=]{10,}", re.IGNORECASE), "Bearer [REDACTED]"),
    # OpenRouter/OpenAI API keys (sk-...)
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}\b"), "[REDACTED_API_KEY]"),
    # OpenRouter keys (or-...)
    (re.compile(r"\bor-[A-Za-z0-9_\-]{20,}\b"), "[REDACTED_API_KEY]"),
    # Anthropic API keys (sk-ant-...)
    (re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}\b"), "[REDACTED_API_KEY]"),
    # Generic API key patterns (api_key=..., apikey=..., key=...)
    (
        re.compile(
            r'(["\']?(?:api[_-]?key|apikey|secret[_-]?key)["\']?\s*[:=]\s*)["\']?[A-Za-z0-9_\-./+=]{16,}["\']?',
            re.IGNORECASE,
        ),
        r"\1[REDACTED]",
    ),
    # Authorization header values in dict/JSON-like contexts
    (
        re.compile(r'(["\']?Authorization["\']?\s*[:=]\s*)["\']?[^"\'}\s]{10,}["\']?', re.IGNORECASE),
        r"\1[REDACTED]",
    ),
    # Token patterns in URLs or query strings
    (
        re.compile(r"([?&](?:token|api_key|key|secret)=)[A-Za-z0-9_\-./+=]{16,}", re.IGNORECASE),
        r"\1[REDACTED]",
    ),
    # Password patterns in URLs (user:pass@host)
    (
        re.compile(r"(://[^:]+:)[^@]+(@)"),
        r"\1[REDACTED]\2",
    ),
]

# Fields that should always be fully redacted if present
SENSITIVE_FIELD_NAMES = frozenset(
    {
        "api_key",
        "apikey",
        "api-key",
        "secret",
        "secret_key",
        "secretkey",
        "password",
        "passwd",
        "token",
        "auth_token",
        "authorization",
        "bearer",
        "credentials",
        "private_key",
        "privatekey",
    }
)


def redact_string(value: str) -> str:
    """Apply all secret patterns to redact sensitive data from a string.

    Args:
        value: The string to redact.

    Returns:
        The redacted string with sensitive patterns replaced.
    """
    result = value
    for pattern, replacement in SECRET_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


def _is_sensitive_key(key: str) -> bool:
    """Check if a key name indicates a sensitive field."""
    normalized = key.lower().replace("-", "_")
    return normalized in SENSITIVE_FIELD_NAMES


def _redact_value(key: str, value: Any) -> Any:
    """Redact a value based on its key name and content."""
    # Fully redact known sensitive field names
    if _is_sensitive_key(key):
        if isinstance(value, str) and value:
            return "[REDACTED]"
        return value

    # Apply pattern-based redaction for string values
    if isinstance(value, str):
        return redact_string(value)

    # Recursively handle dicts
    if isinstance(value, dict):
        return {k: _redact_value(k, v) for k, v in value.items()}

    # Recursively handle lists
    if isinstance(value, list):
        return [_redact_value("", item) for item in value]

    return value


def redact_secrets(
    logger: Any,
    method_name: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    """Structlog processor to redact secrets from log events.

    This processor should be added to the structlog processor chain
    before the final renderer (JSONRenderer, etc.).

    Args:
        logger: The wrapped logger object.
        method_name: The name of the wrapped method (info, warning, etc.).
        event_dict: The event dictionary to process.

    Returns:
        The event dictionary with secrets redacted.
    """
    # Process all keys in the event dict
    redacted = {}
    for key, value in event_dict.items():
        redacted[key] = _redact_value(key, value)
    return redacted


class SecretRedactionFilter(logging.Filter):
    """Stdlib logging filter that redacts secrets from log records.

    This filter applies pattern-based redaction to log messages and
    their arguments before they are emitted.

    Usage:
        logger = logging.getLogger(__name__)
        logger.addFilter(SecretRedactionFilter())
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Apply redaction to the log record.

        Args:
            record: The log record to filter.

        Returns:
            True (always allow the record, after redaction).
        """
        # Redact the main message
        if isinstance(record.msg, str):
            record.msg = redact_string(record.msg)

        # Redact format arguments if present
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: _redact_value(k, v) for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(_redact_value("", arg) if isinstance(arg, str) else arg for arg in record.args)

        # Redact exception info if present
        if record.exc_text:
            record.exc_text = redact_string(record.exc_text)

        return True


def install_stdlib_redaction(logger_name: str | None = None) -> None:
    """Install the redaction filter on a stdlib logger.

    Args:
        logger_name: The logger name to add the filter to. If None,
            adds to the root logger.
    """
    target_logger = logging.getLogger(logger_name)
    # Avoid adding duplicate filters
    for f in target_logger.filters:
        if isinstance(f, SecretRedactionFilter):
            return
    target_logger.addFilter(SecretRedactionFilter())
