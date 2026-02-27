"""Unit tests for harness retry/resume helpers.

Tests for load_api_error_attempts, load_failed_attempts, and load_incomplete_attempts
functions that parse attempt directories and JSON files.
"""

import json
from pathlib import Path

import pytest

from harness.run_harness import (
    load_api_error_attempts,
    load_failed_attempts,
    load_incomplete_attempts,
    retry_api_error_attempts,
    retry_failed_attempts,
)


class TestLoadFailedAttempts:
    """Tests for load_failed_attempts function."""

    def test_load_from_attempts_json(self, tmp_path: Path):
        """Test loading failed attempts from attempts.json."""
        attempts = [
            {"task_id": "task1", "model": "gpt-4", "status": "error"},
            {"task_id": "task2", "model": "gpt-4", "status": "success"},
            {"task_id": "task3", "model": "gpt-4", "status": "fail"},
            {"task_id": "task4", "model": "gpt-4", "status": "api_error"},
            {"task_id": "task5", "model": "gpt-4", "status": "failed"},
        ]
        attempts_file = tmp_path / "attempts.json"
        with attempts_file.open("w") as f:
            json.dump(attempts, f)

        result = load_failed_attempts(tmp_path)

        assert len(result) == 4
        assert result[0]["status"] == "error"
        assert result[1]["status"] == "fail"
        assert result[2]["status"] == "api_error"
        assert result[3]["status"] == "failed"

    def test_load_from_summary_json(self, tmp_path: Path):
        """Test loading failed attempts from summary.json."""
        summary = {
            "attempts": [
                {"task_id": "task1", "model": "gpt-4", "status": "error"},
                {"task_id": "task2", "model": "gpt-4", "status": "success"},
                {"task_id": "task3", "model": "gpt-4", "status": "exception"},
            ]
        }
        summary_file = tmp_path / "summary.json"
        with summary_file.open("w") as f:
            json.dump(summary, f)

        result = load_failed_attempts(tmp_path)

        assert len(result) == 2
        assert result[0]["status"] == "error"
        assert result[1]["status"] == "exception"

    def test_case_insensitive_status_matching(self, tmp_path: Path):
        """Test that status matching is case-insensitive."""
        attempts = [
            {"task_id": "task1", "model": "gpt-4", "status": "ERROR"},
            {"task_id": "task2", "model": "gpt-4", "status": "Fail"},
            {"task_id": "task3", "model": "gpt-4", "status": "API_ERROR"},
        ]
        attempts_file = tmp_path / "attempts.json"
        with attempts_file.open("w") as f:
            json.dump(attempts, f)

        result = load_failed_attempts(tmp_path)

        assert len(result) == 3

    def test_empty_run_directory(self, tmp_path: Path):
        """Test handling of empty run directory."""
        result = load_failed_attempts(tmp_path)
        assert result == []

    def test_attempts_json_takes_precedence(self, tmp_path: Path):
        """Test that attempts.json takes precedence over summary.json."""
        attempts = [{"task_id": "task1", "model": "gpt-4", "status": "error"}]
        attempts_file = tmp_path / "attempts.json"
        with attempts_file.open("w") as f:
            json.dump(attempts, f)

        summary = {"attempts": [{"task_id": "task2", "model": "gpt-4", "status": "fail"}]}
        summary_file = tmp_path / "summary.json"
        with summary_file.open("w") as f:
            json.dump(summary, f)

        result = load_failed_attempts(tmp_path)

        assert len(result) == 1
        assert result[0]["task_id"] == "task1"


class TestLoadApiErrorAttempts:
    """Tests for load_api_error_attempts function."""

    def test_load_from_attempts_json(self, tmp_path: Path):
        """Test loading api_error attempts from attempts.json."""
        attempts = [
            {"task_id": "task1", "model": "gpt-4", "status": "api_error"},
            {"task_id": "task2", "model": "gpt-4", "status": "error"},
            {"task_id": "task3", "model": "gpt-4", "status": "api_error"},
        ]
        attempts_file = tmp_path / "attempts.json"
        with attempts_file.open("w") as f:
            json.dump(attempts, f)

        result = load_api_error_attempts(tmp_path)

        assert len(result) == 2
        assert result[0]["status"] == "api_error"
        assert result[1]["status"] == "api_error"

    def test_load_from_summary_json(self, tmp_path: Path):
        """Test loading api_error attempts from summary.json."""
        summary = {
            "attempts": [
                {"task_id": "task1", "model": "gpt-4", "status": "api_error"},
                {"task_id": "task2", "model": "gpt-4", "status": "success"},
            ]
        }
        summary_file = tmp_path / "summary.json"
        with summary_file.open("w") as f:
            json.dump(summary, f)

        result = load_api_error_attempts(tmp_path)

        assert len(result) == 1
        assert result[0]["status"] == "api_error"

    def test_scan_error_logs_for_rate_limit(self, tmp_path: Path):
        """Test scanning error.log files for RateLimitError."""
        attempt_dir = tmp_path / "task1__gpt-4__sample0__lvl_base"
        attempt_dir.mkdir()
        error_log = attempt_dir / "error.log"
        error_log.write_text("RateLimitError: Rate limit exceeded")

        result = load_api_error_attempts(tmp_path)

        assert len(result) == 1
        assert result[0]["task_id"] == "task1"
        assert result[0]["model"] == "gpt-4"
        assert result[0]["sample_index"] == 0
        assert result[0]["thinking_level_requested"] is None
        assert result[0]["status"] == "api_error"
        assert "RateLimitError" in result[0]["error"]

    def test_scan_error_logs_for_empty_response(self, tmp_path: Path):
        """Test scanning error.log files for EmptyResponseError."""
        attempt_dir = tmp_path / "task2__claude-3-5-sonnet__sample1__lvl_extended"
        attempt_dir.mkdir()
        error_log = attempt_dir / "error.log"
        error_log.write_text("OpenRouter returned empty content")

        result = load_api_error_attempts(tmp_path)

        assert len(result) == 1
        assert result[0]["task_id"] == "task2"
        assert result[0]["model"] == "claude-3-5-sonnet"
        assert result[0]["sample_index"] == 1
        assert result[0]["thinking_level_requested"] == "extended"
        assert "empty content" in result[0]["error"]

    def test_scan_error_logs_for_provider_error(self, tmp_path: Path):
        """Test scanning error.log files for ProviderError."""
        attempt_dir = tmp_path / "task3__o1-preview__sample2__lvl_base"
        attempt_dir.mkdir()
        error_log = attempt_dir / "error.log"
        error_log.write_text("ProviderError: Upstream service unavailable")

        result = load_api_error_attempts(tmp_path)

        assert len(result) == 1
        assert result[0]["status"] == "api_error"
        assert "ProviderError" in result[0]["error"]

    def test_scan_error_logs_for_429_status(self, tmp_path: Path):
        """Test scanning error.log files for 429 status code."""
        attempt_dir = tmp_path / "task4__gpt-4__sample0__lvl_base"
        attempt_dir.mkdir()
        error_log = attempt_dir / "error.log"
        error_log.write_text("HTTP Error 429: Too Many Requests")

        result = load_api_error_attempts(tmp_path)

        assert len(result) == 1
        assert result[0]["status"] == "api_error"
        assert "429" in result[0]["error"]

    def test_does_not_classify_user_code_failures_as_api_error(self, tmp_path: Path):
        """Test that user code failures are not classified as api_error."""
        attempt_dir = tmp_path / "task5__gpt-4__sample0__lvl_base"
        attempt_dir.mkdir()
        error_log = attempt_dir / "error.log"
        error_log.write_text("ValueError: Invalid input from user code")

        result = load_api_error_attempts(tmp_path)

        assert len(result) == 0

    def test_does_not_classify_syntax_errors_as_api_error(self, tmp_path: Path):
        """Test that syntax errors are not classified as api_error."""
        attempt_dir = tmp_path / "task6__gpt-4__sample0__lvl_base"
        attempt_dir.mkdir()
        error_log = attempt_dir / "error.log"
        error_log.write_text("SyntaxError: invalid syntax")

        result = load_api_error_attempts(tmp_path)

        assert len(result) == 0

    def test_parse_directory_name_with_multiple_underscores_in_model(self, tmp_path: Path):
        """Test parsing directory names where model has multiple underscores."""
        attempt_dir = tmp_path / "task7__claude_3_5_sonnet__sample3__lvl_extended"
        attempt_dir.mkdir()
        error_log = attempt_dir / "error.log"
        error_log.write_text("rate limit exceeded")

        result = load_api_error_attempts(tmp_path)

        assert len(result) == 1
        assert result[0]["model"] == "claude/3/5/sonnet"

    def test_parse_directory_name_edge_case_base_level(self, tmp_path: Path):
        """Test that base level is converted to None."""
        attempt_dir = tmp_path / "task8__gpt-4__sample0__lvl_base"
        attempt_dir.mkdir()
        error_log = attempt_dir / "error.log"
        error_log.write_text("RateLimitError")

        result = load_api_error_attempts(tmp_path)

        assert len(result) == 1
        assert result[0]["thinking_level_requested"] is None

    def test_empty_run_directory(self, tmp_path: Path):
        """Test handling of empty run directory."""
        from harness.exceptions import HarnessError

        with pytest.raises(HarnessError, match="Cannot find attempts.json"):
            load_api_error_attempts(tmp_path)

    def test_ignores_non_directory_files(self, tmp_path: Path):
        """Test that non-directory files are ignored."""
        (tmp_path / "random_file.txt").write_text("content")
        result = load_api_error_attempts(tmp_path)
        # Should return empty list because random_file.txt is not a directory
        assert result == []

    def test_ignores_directories_without_error_log(self, tmp_path: Path):
        """Test that directories without error.log are ignored."""
        attempt_dir = tmp_path / "task9__gpt-4__sample0__lvl_base"
        attempt_dir.mkdir()
        result = load_api_error_attempts(tmp_path)
        assert result == []


class TestLoadIncompleteAttempts:
    """Tests for load_incomplete_attempts function."""

    def test_load_incomplete_with_prompt_no_response(self, tmp_path: Path):
        """Test loading incomplete attempts (has prompt.txt, no response)."""
        attempt_dir = tmp_path / "task1__gpt-4__sample0__lvl_base"
        attempt_dir.mkdir()
        (attempt_dir / "prompt.txt").write_text("Test prompt")

        result = load_incomplete_attempts(tmp_path)

        assert len(result) == 1
        assert result[0]["task_id"] == "task1"
        assert result[0]["model"] == "gpt-4"
        assert result[0]["sample_index"] == 0
        assert result[0]["thinking_level"] is None

    def test_load_incomplete_with_thinking_level(self, tmp_path: Path):
        """Test loading incomplete attempts with thinking level."""
        attempt_dir = tmp_path / "task2__claude-3-5-sonnet__sample1__lvl_extended"
        attempt_dir.mkdir()
        (attempt_dir / "prompt.txt").write_text("Test prompt")

        result = load_incomplete_attempts(tmp_path)

        assert len(result) == 1
        assert result[0]["task_id"] == "task2"
        assert result[0]["model"] == "claude-3-5-sonnet"
        assert result[0]["sample_index"] == 1
        assert result[0]["thinking_level"] == "extended"

    def test_ignores_completed_attempts_with_response_txt(self, tmp_path: Path):
        """Test that attempts with response.txt are not considered incomplete."""
        attempt_dir = tmp_path / "task3__gpt-4__sample0__lvl_base"
        attempt_dir.mkdir()
        (attempt_dir / "prompt.txt").write_text("Test prompt")
        (attempt_dir / "response.txt").write_text("Test response")

        result = load_incomplete_attempts(tmp_path)

        assert len(result) == 0

    def test_ignores_completed_attempts_with_response_json(self, tmp_path: Path):
        """Test that attempts with response.json are not considered incomplete."""
        attempt_dir = tmp_path / "task4__gpt-4__sample0__lvl_base"
        attempt_dir.mkdir()
        (attempt_dir / "prompt.txt").write_text("Test prompt")
        (attempt_dir / "response.json").write_text('{"response": "test"}')

        result = load_incomplete_attempts(tmp_path)

        assert len(result) == 0

    def test_ignores_attempts_in_summary(self, tmp_path: Path):
        """Test that attempts already in summary.json are ignored."""
        attempt_dir = tmp_path / "task5__gpt-4__sample0__lvl_base"
        attempt_dir.mkdir()
        (attempt_dir / "prompt.txt").write_text("Test prompt")

        summary = {
            "attempts": [
                {
                    "task_id": "task5",
                    "model": "gpt-4",
                    "sample_index": 0,
                    "thinking_level_applied": "base",
                    "status": "success",
                }
            ]
        }
        summary_file = tmp_path / "summary.json"
        with summary_file.open("w") as f:
            json.dump(summary, f)

        result = load_incomplete_attempts(tmp_path)

        assert len(result) == 0

    def test_handles_multiple_incomplete_attempts(self, tmp_path: Path):
        """Test loading multiple incomplete attempts."""
        for i in range(3):
            attempt_dir = tmp_path / f"task{i}__gpt-4__sample{i}__lvl_base"
            attempt_dir.mkdir()
            (attempt_dir / "prompt.txt").write_text(f"Prompt {i}")

        result = load_incomplete_attempts(tmp_path)

        assert len(result) == 3
        task_ids = {r["task_id"] for r in result}
        assert task_ids == {"task0", "task1", "task2"}

    def test_parse_directory_name_with_sample_number(self, tmp_path: Path):
        """Test parsing directory name with various sample numbers."""
        attempt_dir = tmp_path / "task6__gpt-4__sample42__lvl_base"
        attempt_dir.mkdir()
        (attempt_dir / "prompt.txt").write_text("Test prompt")

        result = load_incomplete_attempts(tmp_path)

        assert len(result) == 1
        assert result[0]["sample_index"] == 42

    def test_parse_directory_name_with_slashes_in_model(self, tmp_path: Path):
        """Test parsing directory names where model contains slashes (converted to underscores)."""
        attempt_dir = tmp_path / "task7__claude_3_5_sonnet__sample0__lvl_base"
        attempt_dir.mkdir()
        (attempt_dir / "prompt.txt").write_text("Test prompt")

        result = load_incomplete_attempts(tmp_path)

        assert len(result) == 1
        assert result[0]["model"] == "claude/3/5/sonnet"

    def test_parse_directory_name_with_slashes_in_thinking_level(self, tmp_path: Path):
        """Test parsing thinking level with slashes (converted to underscores)."""
        attempt_dir = tmp_path / "task8__gpt-4__sample0__lvl_o1_preview"
        attempt_dir.mkdir()
        (attempt_dir / "prompt.txt").write_text("Test prompt")

        result = load_incomplete_attempts(tmp_path)

        assert len(result) == 1
        assert result[0]["thinking_level"] == "o1/preview"

    def test_ignores_directories_without_prompt(self, tmp_path: Path):
        """Test that directories without prompt.txt are ignored."""
        attempt_dir = tmp_path / "task9__gpt-4__sample0__lvl_base"
        attempt_dir.mkdir()

        result = load_incomplete_attempts(tmp_path)

        assert len(result) == 0

    def test_ignores_non_directory_files(self, tmp_path: Path):
        """Test that non-directory files are ignored."""
        (tmp_path / "summary.json").write_text('{"attempts": []}')
        (tmp_path / "random_file.txt").write_text("content")

        result = load_incomplete_attempts(tmp_path)

        assert len(result) == 0

    def test_parse_directory_name_with_insufficient_parts(self, tmp_path: Path):
        """Test that directory names with insufficient parts are skipped."""
        attempt_dir = tmp_path / "invalid__dir"
        attempt_dir.mkdir()
        (attempt_dir / "prompt.txt").write_text("Test prompt")

        result = load_incomplete_attempts(tmp_path)

        assert len(result) == 0

    def test_empty_run_directory(self, tmp_path: Path):
        """Test handling of empty run directory."""
        result = load_incomplete_attempts(tmp_path)
        assert result == []

    def test_base_level_converted_to_none(self, tmp_path: Path):
        """Test that base thinking level is converted to None."""
        attempt_dir = tmp_path / "task10__gpt-4__sample0__lvl_base"
        attempt_dir.mkdir()
        (attempt_dir / "prompt.txt").write_text("Test prompt")

        result = load_incomplete_attempts(tmp_path)

        assert len(result) == 1
        assert result[0]["thinking_level"] is None

    def test_attempt_dir_path_included(self, tmp_path: Path):
        """Test that attempt_dir path is included in result."""
        attempt_dir = tmp_path / "task11__gpt-4__sample0__lvl_base"
        attempt_dir.mkdir()
        (attempt_dir / "prompt.txt").write_text("Test prompt")

        result = load_incomplete_attempts(tmp_path)

        assert len(result) == 1
        assert result[0]["attempt_dir"] == str(attempt_dir)

    def test_summary_uses_thinking_level_applied_or_requested(self, tmp_path: Path):
        """Test that summary.json uses thinking_level_applied or falls back to thinking_level_requested."""
        attempt_dir = tmp_path / "task12__gpt-4__sample0__lvl_extended"
        attempt_dir.mkdir()
        (attempt_dir / "prompt.txt").write_text("Test prompt")

        summary = {
            "attempts": [
                {
                    "task_id": "task12",
                    "model": "gpt-4",
                    "sample_index": 0,
                    "thinking_level_requested": "extended",
                    "status": "success",
                }
            ]
        }
        summary_file = tmp_path / "summary.json"
        with summary_file.open("w") as f:
            json.dump(summary, f)

        result = load_incomplete_attempts(tmp_path)

        # Should be ignored because it's in summary (using thinking_level_requested)
        assert len(result) == 0

    def test_invalid_sample_number_defaults_to_zero(self, tmp_path: Path):
        """Test that invalid sample numbers default to 0."""
        attempt_dir = tmp_path / "task13__gpt-4__sampleXYZ__lvl_base"
        attempt_dir.mkdir()
        (attempt_dir / "prompt.txt").write_text("Test prompt")

        result = load_incomplete_attempts(tmp_path)

        assert len(result) == 1
        assert result[0]["sample_index"] == 0


class TestRetryMetricsMerging:
    """Tests ensuring retry summaries preserve full-run accuracy context."""

    @staticmethod
    def _write_original_run(run_dir: Path, attempts: list[dict]) -> None:
        summary = {
            "timestamp_utc": "2026-02-27T15:03:46.000000+00:00",
            "run_id": run_dir.name,
            "run_dir": str(run_dir),
            "tasks": ["task1", "task2", "task3"],
            "models": ["test/model"],
            "samples": 1,
            "thinking_level": "high",
            "attempts": attempts,
        }
        (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        (run_dir / "attempts.json").write_text(json.dumps(attempts, indent=2), encoding="utf-8")

    @staticmethod
    def _stub_evaluate_attempt(task_id: str, model: str, sample_index: int, **_: dict) -> dict:
        return {
            "task_id": task_id,
            "model": model,
            "sample_index": sample_index,
            "status": "passed",
            "duration_seconds": 1.0,
            "api_latency_seconds": 0.2,
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            "cost_usd": 0.01,
            "thinking_level_requested": "high",
            "thinking_level_supported": True,
            "thinking_level_applied": "high",
            "attempt_dir": f"{task_id}__test_model__sample{sample_index}__lvl_high",
        }

    def test_retry_failed_attempts_recomputes_full_run_accuracy(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        original_run = tmp_path / "run_original"
        original_run.mkdir()
        attempts = [
            {"task_id": "task1", "model": "test/model", "sample_index": 0, "status": "passed"},
            {"task_id": "task2", "model": "test/model", "sample_index": 0, "status": "failed"},
            {"task_id": "task3", "model": "test/model", "sample_index": 0, "status": "failed"},
        ]
        self._write_original_run(original_run, attempts)

        monkeypatch.setattr("harness.run_harness.RUN_ARTIFACTS", tmp_path)
        monkeypatch.setattr("harness.run_harness.fetch_model_metadata", lambda models: {m: {} for m in models})
        monkeypatch.setattr("harness.run_harness.load_metadata", lambda task_id: {})
        monkeypatch.setattr("harness.run_harness.evaluate_attempt", self._stub_evaluate_attempt)
        monkeypatch.setattr("harness.run_harness.update_task_latest", lambda *_args, **_kwargs: None)
        monkeypatch.setattr("harness.run_harness._is_lmstudio_model", lambda _model: False)

        summary = retry_failed_attempts(
            original_run_dir=original_run,
            output_dir=tmp_path,
            run_id="run_retry_failed",
            filter_task_id="task2",
        )

        assert summary["retried_count"] == 1
        assert len(summary["attempts"]) == 3
        status_by_task = {a["task_id"]: a["status"] for a in summary["attempts"]}
        assert status_by_task == {"task1": "passed", "task2": "passed", "task3": "failed"}
        assert summary["metrics"]["overall"]["macro_model_accuracy"] == pytest.approx(2 / 3)

    def test_retry_api_error_attempts_recomputes_full_run_accuracy(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        original_run = tmp_path / "run_original_api"
        original_run.mkdir()
        attempts = [
            {"task_id": "task1", "model": "test/model", "sample_index": 0, "status": "passed"},
            {"task_id": "task2", "model": "test/model", "sample_index": 0, "status": "api_error"},
            {"task_id": "task3", "model": "test/model", "sample_index": 0, "status": "failed"},
        ]
        self._write_original_run(original_run, attempts)

        monkeypatch.setattr("harness.run_harness.RUN_ARTIFACTS", tmp_path)
        monkeypatch.setattr("harness.run_harness.fetch_model_metadata", lambda models: {m: {} for m in models})
        monkeypatch.setattr("harness.run_harness.load_metadata", lambda task_id: {})
        monkeypatch.setattr("harness.run_harness.evaluate_attempt", self._stub_evaluate_attempt)
        monkeypatch.setattr("harness.run_harness.update_task_latest", lambda *_args, **_kwargs: None)
        monkeypatch.setattr("harness.run_harness._is_lmstudio_model", lambda _model: False)

        summary = retry_api_error_attempts(
            original_run_dir=original_run,
            output_dir=tmp_path,
            run_id="run_retry_api",
        )

        assert summary["retried_count"] == 1
        assert len(summary["attempts"]) == 3
        status_by_task = {a["task_id"]: a["status"] for a in summary["attempts"]}
        assert status_by_task == {"task1": "passed", "task2": "passed", "task3": "failed"}
        assert summary["metrics"]["overall"]["macro_model_accuracy"] == pytest.approx(2 / 3)
