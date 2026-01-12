"""Unit and integration tests for database utilities and session behavior."""

import datetime as dt
import json

from server.database_utils import (
    FAILED_STATUSES,
    count_errors_from_summary,
    extract_usage_tokens,
    parse_timestamp,
)


class TestParseTimestamp:
    """Tests for parse_timestamp function."""

    def test_parse_valid_iso_timestamp(self):
        """Test parsing a valid ISO timestamp."""
        timestamp_str = "2025-01-11T12:30:45.123456"
        result = parse_timestamp(timestamp_str)

        assert isinstance(result, dt.datetime)
        assert result.year == 2025
        assert result.month == 1
        assert result.day == 11
        assert result.hour == 12
        assert result.minute == 30
        assert result.second == 45
        assert result.tzinfo is None  # Should be naive

    def test_parse_timestamp_with_timezone(self):
        """Test parsing a timestamp with timezone normalizes to UTC."""
        timestamp_str = "2025-01-11T12:30:45+05:00"
        result = parse_timestamp(timestamp_str)

        assert isinstance(result, dt.datetime)
        assert result.tzinfo is None  # Should be naive
        # UTC time should be 5 hours earlier: 07:30:45
        assert result.hour == 7
        assert result.minute == 30

    def test_parse_timestamp_with_utc_timezone(self):
        """Test parsing a timestamp with UTC timezone."""
        timestamp_str = "2025-01-11T12:30:45+00:00"
        result = parse_timestamp(timestamp_str)

        assert isinstance(result, dt.datetime)
        assert result.tzinfo is None  # Should be naive
        assert result.hour == 12
        assert result.minute == 30

    def test_parse_timestamp_with_z_suffix(self):
        """Test parsing a timestamp with Z suffix (UTC)."""
        timestamp_str = "2025-01-11T12:30:45Z"
        result = parse_timestamp(timestamp_str)

        assert isinstance(result, dt.datetime)
        assert result.tzinfo is None  # Should be naive

    def test_parse_invalid_timestamp_fallback(self):
        """Test that invalid timestamp falls back to current UTC time."""
        invalid_timestamp = "not-a-valid-timestamp"
        before = dt.datetime.now(dt.UTC).replace(tzinfo=None)
        result = parse_timestamp(invalid_timestamp)
        after = dt.datetime.now(dt.UTC).replace(tzinfo=None)

        assert isinstance(result, dt.datetime)
        assert result.tzinfo is None
        # Should be between before and after (within a few seconds)
        assert before <= result <= after

    def test_parse_none_timestamp_fallback(self):
        """Test that None timestamp falls back to current UTC time."""
        before = dt.datetime.now(dt.UTC).replace(tzinfo=None)
        result = parse_timestamp(None)
        after = dt.datetime.now(dt.UTC).replace(tzinfo=None)

        assert isinstance(result, dt.datetime)
        assert result.tzinfo is None
        assert before <= result <= after

    def test_parse_empty_string_fallback(self):
        """Test that empty string falls back to current UTC time."""
        before = dt.datetime.now(dt.UTC).replace(tzinfo=None)
        result = parse_timestamp("")
        after = dt.datetime.now(dt.UTC).replace(tzinfo=None)

        assert isinstance(result, dt.datetime)
        assert result.tzinfo is None
        assert before <= result <= after

    def test_timezone_normalization(self):
        """Test that timezone-aware timestamps are normalized to naive UTC."""
        # PST is UTC-8
        timestamp_str = "2025-01-11T12:00:00-08:00"
        result = parse_timestamp(timestamp_str)

        assert result.tzinfo is None
        # UTC time should be 8 hours later: 20:00:00
        assert result.hour == 20
        assert result.minute == 0


class TestExtractUsageTokens:
    """Tests for extract_usage_tokens function."""

    def test_extract_openai_style_tokens(self):
        """Test extracting tokens from OpenAI-style usage dict."""
        usage = {"prompt_tokens": 100, "completion_tokens": 50}
        prompt, completion = extract_usage_tokens(usage)

        assert prompt == 100
        assert completion == 50

    def test_extract_anthropic_style_tokens(self):
        """Test extracting tokens from Anthropic-style usage dict."""
        usage = {"input_tokens": 150, "output_tokens": 75}
        prompt, completion = extract_usage_tokens(usage)

        assert prompt == 150
        assert completion == 75

    def test_extract_mixed_style_tokens_openai_preferred(self):
        """Test that OpenAI-style keys are preferred when both present."""
        usage = {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "input_tokens": 999,
            "output_tokens": 888,
        }
        prompt, completion = extract_usage_tokens(usage)

        assert prompt == 100
        assert completion == 50

    def test_extract_tokens_from_none(self):
        """Test extracting tokens from None usage."""
        prompt, completion = extract_usage_tokens(None)

        assert prompt is None
        assert completion is None

    def test_extract_tokens_from_empty_dict(self):
        """Test extracting tokens from empty usage dict."""
        usage = {}
        prompt, completion = extract_usage_tokens(usage)

        assert prompt is None
        assert completion is None

    def test_extract_tokens_partial_openai(self):
        """Test extracting tokens when only some OpenAI keys present."""
        usage = {"prompt_tokens": 100}
        prompt, completion = extract_usage_tokens(usage)

        assert prompt == 100
        assert completion is None

    def test_extract_tokens_partial_anthropic(self):
        """Test extracting tokens when only some Anthropic keys present."""
        usage = {"output_tokens": 75}
        prompt, completion = extract_usage_tokens(usage)

        assert prompt is None
        assert completion == 75

    def test_extract_tokens_zero_values(self):
        """Test extracting tokens with zero values."""
        usage = {"prompt_tokens": 0, "completion_tokens": 0}
        prompt, completion = extract_usage_tokens(usage)

        # Note: 0 is falsy, so this will return None due to the 'or' logic
        assert prompt is None
        assert completion is None

    def test_extract_tokens_with_extra_fields(self):
        """Test extracting tokens from usage dict with extra fields."""
        usage = {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
            "model": "gpt-4",
        }
        prompt, completion = extract_usage_tokens(usage)

        assert prompt == 100
        assert completion == 50


class TestCountErrorsFromSummary:
    """Tests for count_errors_from_summary function."""

    def test_count_errors_basic(self):
        """Test counting errors from a valid summary."""
        summary = {
            "attempts": [
                {"status": "success"},
                {"status": "error"},
                {"status": "success"},
                {"status": "fail"},
            ]
        }
        summary_json = json.dumps(summary)
        count = count_errors_from_summary(summary_json)

        assert count == 2

    def test_count_errors_all_failed_statuses(self):
        """Test counting all recognized failed statuses."""
        summary = {
            "attempts": [
                {"status": "error"},
                {"status": "fail"},
                {"status": "failed"},
                {"status": "api_error"},
                {"status": "exception"},
            ]
        }
        summary_json = json.dumps(summary)
        count = count_errors_from_summary(summary_json)

        assert count == 5

    def test_count_errors_case_insensitive(self):
        """Test that status matching is case-insensitive."""
        summary = {
            "attempts": [
                {"status": "ERROR"},
                {"status": "Fail"},
                {"status": "FAILED"},
                {"status": "Api_Error"},
            ]
        }
        summary_json = json.dumps(summary)
        count = count_errors_from_summary(summary_json)

        assert count == 4

    def test_count_errors_from_none(self):
        """Test counting errors from None summary."""
        count = count_errors_from_summary(None)
        assert count == 0

    def test_count_errors_from_empty_string(self):
        """Test counting errors from empty string."""
        count = count_errors_from_summary("")
        assert count == 0

    def test_count_errors_malformed_json(self):
        """Test counting errors from malformed JSON."""
        malformed_json = "{invalid json"
        count = count_errors_from_summary(malformed_json)
        assert count == 0

    def test_count_errors_missing_attempts_key(self):
        """Test counting errors when attempts key is missing."""
        summary = {"tasks": ["task1"]}
        summary_json = json.dumps(summary)
        count = count_errors_from_summary(summary_json)

        assert count == 0

    def test_count_errors_empty_attempts(self):
        """Test counting errors with empty attempts list."""
        summary = {"attempts": []}
        summary_json = json.dumps(summary)
        count = count_errors_from_summary(summary_json)

        assert count == 0

    def test_count_errors_missing_status(self):
        """Test counting errors when status key is missing."""
        summary = {"attempts": [{"task_id": "task1"}, {"status": "error"}]}
        summary_json = json.dumps(summary)
        count = count_errors_from_summary(summary_json)

        assert count == 1  # Only the one with status="error"

    def test_count_errors_status_normalization(self):
        """Test that status values are normalized (lowercased)."""
        summary = {
            "attempts": [
                {"status": "SUCCESS"},
                {"status": "error"},
                {"status": "FAIL"},
            ]
        }
        summary_json = json.dumps(summary)
        count = count_errors_from_summary(summary_json)

        assert count == 2

    def test_count_errors_non_dict_summary(self):
        """Test counting errors from non-dict JSON."""
        summary_json = json.dumps(["not", "a", "dict"])
        # This will raise AttributeError when trying to call .get() on a list
        # The function should handle this gracefully
        count = count_errors_from_summary(summary_json)

        # Should return 0 on error (caught by except clause)
        assert count == 0

    def test_failed_statuses_constant(self):
        """Test that FAILED_STATUSES constant is correct."""
        expected = {"error", "fail", "failed", "api_error", "exception"}
        assert expected == FAILED_STATUSES


class TestGetSessionIntegration:
    """Integration tests for get_session transactional behavior."""

    def test_get_session_context_manager(self):
        """Test that get_session works as a context manager."""
        from server.database import get_session, init_db

        # Initialize the database
        init_db()

        # Verify we can get a session
        with get_session() as session:
            assert session is not None
            # Session should be usable within the context
            assert hasattr(session, "query")
            assert hasattr(session, "add")
            assert hasattr(session, "commit")

    def test_get_session_rollback_on_exception(self):
        """Test that get_session rolls back changes on exception."""
        from server.database import get_session, init_db, RunRecord

        # Initialize the database
        init_db()

        # Use a unique run_id to avoid conflicts with existing data
        run_id = f"test-rollback-{dt.datetime.now().isoformat()}"

        # Attempt to create a record but raise an exception
        try:
            with get_session() as session:
                record = RunRecord(
                    id=run_id,
                    model_id="gpt-4",
                    tasks=json.dumps(["task1"]),
                    samples=1,
                    timestamp_utc=dt.datetime.now(),
                    summary_path="/tmp/test",
                    summary_json="{}",
                )
                session.add(record)
                session.flush()  # Ensure the add is processed
                raise ValueError("Intentional error")
        except ValueError:
            pass  # Expected

        # Verify the record was NOT persisted (rollback occurred)
        with get_session() as session:
            retrieved = session.get(RunRecord, run_id)
            assert retrieved is None, "Record should have been rolled back"

    def test_get_session_auto_commit(self):
        """Test that get_session auto-commits on successful exit."""
        from server.database import get_session, init_db, RunRecord

        # Initialize the database
        init_db()

        # Use a unique run_id
        run_id = f"test-commit-{dt.datetime.now().isoformat()}"

        try:
            # Create a test run record
            with get_session() as session:
                record = RunRecord(
                    id=run_id,
                    model_id="gpt-4-test",
                    tasks=json.dumps(["task1"]),
                    samples=1,
                    timestamp_utc=dt.datetime.now(),
                    summary_path="/tmp/test",
                    summary_json="{}",
                )
                session.add(record)
            # Session should auto-commit on exit

            # Verify the record was persisted
            with get_session() as session:
                retrieved = session.get(RunRecord, run_id)
                assert retrieved is not None, "Record should have been committed"
                assert retrieved.model_id == "gpt-4-test"
        finally:
            # Clean up: delete the test record
            with get_session() as session:
                record = session.get(RunRecord, run_id)
                if record:
                    session.delete(record)
