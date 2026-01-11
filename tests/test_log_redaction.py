"""Tests for log redaction utilities to prevent secret/PII leakage.

These tests verify that:
1. Common secret patterns are properly redacted
2. Structlog processor handles all field types
3. Stdlib logging filter works correctly
4. Redaction is deterministic and avoids false positives
"""

from __future__ import annotations

import logging
from io import StringIO

import pytest

from server.redaction import (
    SecretRedactionFilter,
    install_stdlib_redaction,
    redact_secrets,
    redact_string,
)


class TestRedactString:
    """Tests for the redact_string function."""

    def test_bearer_token_redacted(self) -> None:
        """Bearer tokens are redacted."""
        assert redact_string("Bearer sk-abcdef1234567890abcdef") == "Bearer [REDACTED]"
        assert redact_string("Authorization: Bearer my-secret-token-value") == "Authorization: Bearer [REDACTED]"

    def test_openai_key_redacted(self) -> None:
        """OpenAI-style API keys (sk-...) are redacted."""
        assert redact_string("Using key sk-1234567890abcdef1234567890abcdef") == "Using key [REDACTED_API_KEY]"

    def test_openrouter_key_redacted(self) -> None:
        """OpenRouter API keys (or-...) are redacted."""
        assert redact_string("Key is or-1234567890abcdef1234567890abcdef") == "Key is [REDACTED_API_KEY]"

    def test_anthropic_key_redacted(self) -> None:
        """Anthropic API keys (sk-ant-...) are redacted."""
        assert redact_string("sk-ant-1234567890abcdef1234567890abcdef is my key") == "[REDACTED_API_KEY] is my key"

    def test_generic_api_key_pattern_redacted(self) -> None:
        """Generic api_key=... patterns are redacted."""
        # The pattern captures quotes as part of the match, so result includes quotes in [REDACTED]
        assert "api_key=[REDACTED]" in redact_string('api_key="secretvalue12345678"')
        assert "apikey=[REDACTED]" in redact_string("apikey=mysecret1234567890")
        assert "secret_key:[REDACTED]" in redact_string("secret_key:verysecretvalue123456")

    def test_authorization_header_redacted(self) -> None:
        """Authorization header values are redacted."""
        assert "Authorization: [REDACTED]" in redact_string("Authorization: supersecrettoken12345")
        # Bearer tokens are matched first, so Bearer pattern takes precedence
        result = redact_string('{"Authorization":"Bearer tokentokentoken"}')
        assert "Bearer [REDACTED]" in result or '"Authorization":[REDACTED]' in result

    def test_url_token_params_redacted(self) -> None:
        """Token parameters in URLs are redacted."""
        assert "token=[REDACTED]" in redact_string("https://api.example.com?token=secrettoken12345678")
        assert "api_key=[REDACTED]" in redact_string("https://example.com?api_key=key123456789012345")

    def test_password_in_url_redacted(self) -> None:
        """Passwords in URLs (user:pass@host) are redacted."""
        assert "://user:[REDACTED]@" in redact_string("postgresql://user:secretpassword@host:5432/db")

    def test_short_tokens_not_redacted(self) -> None:
        """Short values that don't meet length thresholds are not redacted."""
        # Short bearer token (< 10 chars) should not match
        assert redact_string("Bearer abc") == "Bearer abc"
        # Short sk- pattern (< 20 chars after prefix) should not match
        assert redact_string("sk-short") == "sk-short"

    def test_safe_content_not_redacted(self) -> None:
        """Regular content without secret patterns is unchanged."""
        safe_text = "This is a normal log message about user activity."
        assert redact_string(safe_text) == safe_text

        safe_json = '{"status": "ok", "count": 42}'
        assert redact_string(safe_json) == safe_json

    def test_multiple_secrets_all_redacted(self) -> None:
        """Multiple secrets in the same string are all redacted."""
        text = "Key1: sk-1234567890abcdef12345678 and " "Key2: Bearer mysupersecrettoken123"
        redacted = redact_string(text)
        assert "sk-" not in redacted or "[REDACTED_API_KEY]" in redacted
        assert "Bearer [REDACTED]" in redacted

    def test_case_insensitive_patterns(self) -> None:
        """Patterns match case-insensitively where appropriate."""
        # Case-insensitive matching, but replacement is normalized to "Bearer [REDACTED]"
        result_bearer = redact_string("BEARER mysupersecrettoken1234")
        assert "Bearer [REDACTED]" in result_bearer or "[REDACTED]" in result_bearer
        # API_KEY pattern matches case-insensitively
        assert "API_KEY=[REDACTED]" in redact_string("API_KEY=verysecretvalue12345678")


class TestRedactSecretsProcessor:
    """Tests for the structlog processor."""

    def test_event_field_redacted(self) -> None:
        """The event field is redacted if it contains secrets."""
        event_dict = {"event": "Error with Bearer secrettoken12345678"}
        result = redact_secrets(None, "info", event_dict)
        assert "Bearer [REDACTED]" in result["event"]

    def test_error_field_redacted(self) -> None:
        """Error fields containing secrets are redacted."""
        event_dict = {
            "event": "api.failed",
            "error": "Invalid API key: sk-12345678901234567890abcd",
        }
        result = redact_secrets(None, "error", event_dict)
        assert "[REDACTED_API_KEY]" in result["error"]

    def test_sensitive_field_name_fully_redacted(self) -> None:
        """Fields with sensitive names are fully redacted."""
        event_dict = {
            "event": "request",
            "api_key": "my-secret-key",
            "authorization": "Bearer token123",
            "password": "supersecret",
        }
        result = redact_secrets(None, "info", event_dict)
        assert result["api_key"] == "[REDACTED]"
        assert result["authorization"] == "[REDACTED]"
        assert result["password"] == "[REDACTED]"

    def test_nested_dict_redacted(self) -> None:
        """Nested dictionaries are recursively redacted."""
        event_dict = {
            "event": "request",
            "headers": {
                "Authorization": "Bearer secretvalue123456",
                "Content-Type": "application/json",
            },
        }
        result = redact_secrets(None, "info", event_dict)
        assert result["headers"]["Authorization"] == "[REDACTED]"
        assert result["headers"]["Content-Type"] == "application/json"

    def test_list_values_redacted(self) -> None:
        """List values are recursively redacted."""
        event_dict = {
            "event": "multi-key",
            "keys": [
                "sk-1234567890abcdef12345678",
                "normal-value",
                "sk-abcdef1234567890abcdef12",
            ],
        }
        result = redact_secrets(None, "info", event_dict)
        assert "[REDACTED_API_KEY]" in result["keys"][0]
        assert result["keys"][1] == "normal-value"
        assert "[REDACTED_API_KEY]" in result["keys"][2]

    def test_non_string_values_unchanged(self) -> None:
        """Non-string values pass through unchanged."""
        event_dict = {
            "event": "metrics",
            "count": 42,
            "ratio": 0.75,
            "enabled": True,
            "items": None,
        }
        result = redact_secrets(None, "info", event_dict)
        assert result["count"] == 42
        assert result["ratio"] == 0.75
        assert result["enabled"] is True
        assert result["items"] is None


class TestSecretRedactionFilter:
    """Tests for the stdlib logging filter."""

    @pytest.fixture
    def logger_with_filter(self) -> tuple[logging.Logger, StringIO]:
        """Create a logger with the redaction filter and capture output."""
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter("%(message)s"))

        logger = logging.getLogger("test_redaction_filter")
        logger.setLevel(logging.DEBUG)
        logger.handlers = [handler]
        logger.addFilter(SecretRedactionFilter())

        return logger, stream

    def test_message_redacted(self, logger_with_filter: tuple[logging.Logger, StringIO]) -> None:
        """Log messages containing secrets are redacted."""
        logger, stream = logger_with_filter
        logger.info("API key is sk-1234567890abcdef12345678901234")
        output = stream.getvalue()
        assert "[REDACTED_API_KEY]" in output
        assert "sk-1234567890" not in output

    def test_format_args_redacted(self, logger_with_filter: tuple[logging.Logger, StringIO]) -> None:
        """Format arguments containing secrets are redacted."""
        logger, stream = logger_with_filter
        logger.info("Token: %s", "Bearer supersecrettoken12345")
        output = stream.getvalue()
        assert "Bearer [REDACTED]" in output

    def test_dict_args_redacted(self, logger_with_filter: tuple[logging.Logger, StringIO]) -> None:
        """Dict-style format arguments with sensitive keys are redacted."""
        logger, stream = logger_with_filter
        logger.info("Request: %(api_key)s", {"api_key": "secret123"})
        output = stream.getvalue()
        assert "[REDACTED]" in output

    def test_filter_always_returns_true(self) -> None:
        """Filter always returns True (allows record after redaction)."""
        filter_instance = SecretRedactionFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="test message",
            args=(),
            exc_info=None,
        )
        assert filter_instance.filter(record) is True


class TestInstallStdlibRedaction:
    """Tests for the install_stdlib_redaction helper."""

    def test_filter_installed(self) -> None:
        """Filter is installed on the target logger."""
        logger = logging.getLogger("test_install_redaction")
        # Clear existing filters
        logger.filters = []

        install_stdlib_redaction("test_install_redaction")

        assert any(isinstance(f, SecretRedactionFilter) for f in logger.filters)

    def test_no_duplicate_filters(self) -> None:
        """Calling install multiple times does not add duplicate filters."""
        logger = logging.getLogger("test_no_duplicates")
        logger.filters = []

        install_stdlib_redaction("test_no_duplicates")
        install_stdlib_redaction("test_no_duplicates")
        install_stdlib_redaction("test_no_duplicates")

        filter_count = sum(1 for f in logger.filters if isinstance(f, SecretRedactionFilter))
        assert filter_count == 1


class TestRedactionDeterminism:
    """Tests to ensure redaction is deterministic and consistent."""

    def test_same_input_same_output(self) -> None:
        """Same input always produces the same output."""
        secret = "Bearer sk-1234567890abcdef1234567890abcdef1234"
        result1 = redact_string(secret)
        result2 = redact_string(secret)
        assert result1 == result2

    def test_no_false_positives_on_common_words(self) -> None:
        """Common words that might partially match patterns are not redacted."""
        # 'token' is a common word but shouldn't be redacted unless in context
        text = "The token count is 1000"
        assert redact_string(text) == text

        # 'key' is common but shouldn't be redacted in normal contexts
        text = "Press the key to continue"
        assert redact_string(text) == text

    def test_error_messages_with_secrets_redacted(self) -> None:
        """Error messages containing secrets are properly redacted."""
        error_msg = (
            "Failed to authenticate: Invalid API key 'sk-1234567890abcdef1234567890'. "
            "Please check your OPENROUTER_API_KEY environment variable."
        )
        redacted = redact_string(error_msg)
        assert "[REDACTED_API_KEY]" in redacted
        assert "sk-1234567890" not in redacted
        # The variable name mention should remain (it's not a secret value)
        assert "OPENROUTER_API_KEY" in redacted

    def test_exception_traceback_redacted(self) -> None:
        """Secrets in exception tracebacks are redacted."""
        traceback_text = """
Traceback (most recent call last):
  File "/app/harness/run_harness.py", line 354, in make_request
    headers = {"Authorization": "Bearer sk-prod-12345678901234567890abcdef"}
requests.exceptions.HTTPError: 401 Client Error: Unauthorized
"""
        redacted = redact_string(traceback_text)
        assert "Bearer [REDACTED]" in redacted
        assert "sk-prod-" not in redacted


class TestRepresentativeLoggingPaths:
    """Integration tests for representative logging scenarios."""

    def test_structlog_api_error_redacted(self) -> None:
        """API errors logged via structlog have secrets redacted."""
        event_dict = {
            "event": "api.error",
            "error": "Authentication failed with key sk-test-1234567890abcdef1234567890",
            "status_code": 401,
            "response": '{"error": "Invalid Authorization header: Bearer badtoken123456789"}',
        }
        result = redact_secrets(None, "error", event_dict)

        assert "[REDACTED_API_KEY]" in result["error"]
        assert "Bearer [REDACTED]" in result["response"]

    def test_structlog_request_headers_redacted(self) -> None:
        """Request headers logged via structlog have secrets redacted."""
        event_dict = {
            "event": "http.request",
            "method": "POST",
            "url": "https://api.openrouter.ai/api/v1/chat/completions",
            "headers": {
                "Authorization": "Bearer or-v1-1234567890abcdef1234567890",
                "Content-Type": "application/json",
                "User-Agent": "benchmark-harness/1.0",
            },
        }
        result = redact_secrets(None, "info", event_dict)

        assert result["headers"]["Authorization"] == "[REDACTED]"
        assert result["headers"]["Content-Type"] == "application/json"
        assert result["headers"]["User-Agent"] == "benchmark-harness/1.0"

    def test_harness_logger_redacts_secrets(self) -> None:
        """The harness logger (stdlib) redacts secrets properly."""
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter("%(message)s"))

        logger = logging.getLogger("harness.test")
        logger.setLevel(logging.DEBUG)
        logger.handlers = [handler]
        logger.addFilter(SecretRedactionFilter())

        # Simulate typical harness log message
        logger.warning(
            "Failed to fetch from OpenRouter: 401 Unauthorized. " "Key: sk-or-v1-1234567890abcdef1234567890abcdef1234"
        )

        output = stream.getvalue()
        assert "[REDACTED_API_KEY]" in output
        assert "sk-or-v1-" not in output
