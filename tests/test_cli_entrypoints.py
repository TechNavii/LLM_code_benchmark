"""Smoke tests for harness CLI entrypoints and argument parsing.

These tests invoke the harness CLI via subprocess to verify:
- --help output is stable and correct
- Argument parsing works for minimal inputs
- Exit codes match expected behavior
- Dry-run mode works without network calls

Tests are hermetic (no network, no task execution, temp dirs only) and fast.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest


# Use a task that's known to exist in the catalog
KNOWN_TASK = "python_expert_workflow_scheduler"
# Fallback to another task if the first doesn't exist
FALLBACK_TASKS = ["go_expert_lru_cache", "go_expert_scheduler", "javascript_bugfix_titlecase"]

# Timeout for subprocess calls (seconds)
SUBPROCESS_TIMEOUT = 30


def get_available_task() -> str | None:
    """Find an available task from the tasks directory."""
    project_root = Path(__file__).parent.parent
    tasks_dir = project_root / "tasks"
    if not tasks_dir.exists():
        return None

    # Try known task first
    if (tasks_dir / KNOWN_TASK).is_dir():
        return KNOWN_TASK

    # Try fallback tasks
    for task in FALLBACK_TASKS:
        if (tasks_dir / task).is_dir():
            return task

    # Use first available task
    for item in tasks_dir.iterdir():
        if item.is_dir() and not item.name.startswith("."):
            return item.name

    return None


class TestHelpOutput:
    """Tests for --help output stability."""

    def test_help_exits_zero(self) -> None:
        """Invoking --help should exit with code 0."""
        result = subprocess.run(
            [sys.executable, "-m", "harness.run_harness", "--help"],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"

    def test_help_contains_description(self) -> None:
        """--help output should contain the harness description."""
        result = subprocess.run(
            [sys.executable, "-m", "harness.run_harness", "--help"],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT,
        )
        assert "OpenRouter benchmark harness" in result.stdout

    def test_help_contains_required_arguments(self) -> None:
        """--help output should document key CLI arguments."""
        result = subprocess.run(
            [sys.executable, "-m", "harness.run_harness", "--help"],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT,
        )
        output = result.stdout

        # Core task selection arguments
        assert "--task" in output
        assert "--tasks" in output
        assert "--models" in output

        # Run configuration
        assert "--samples" in output
        assert "--temperature" in output
        assert "--max-tokens" in output

        # Execution modes
        assert "--dry-run" in output
        assert "--response-file" in output
        assert "--output-dir" in output

        # Resume/retry modes
        assert "--resume-from" in output
        assert "--retry-api-errors" in output
        assert "--resume-incomplete" in output

    def test_help_contains_thinking_options(self) -> None:
        """--help output should document thinking-related arguments."""
        result = subprocess.run(
            [sys.executable, "-m", "harness.run_harness", "--help"],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT,
        )
        output = result.stdout

        assert "--thinking-level" in output
        assert "--include-thinking-variants" in output
        assert "--sweep-thinking-levels" in output

    def test_help_contains_diff_options(self) -> None:
        """--help output should document diff handling arguments."""
        result = subprocess.run(
            [sys.executable, "-m", "harness.run_harness", "--help"],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT,
        )
        output = result.stdout

        assert "--allow-incomplete-diffs" in output
        assert "--no-allow-incomplete-diffs" in output
        assert "--allow-diff-rewrite-fallback" in output
        assert "--no-allow-diff-rewrite-fallback" in output


class TestArgumentParsing:
    """Tests for CLI argument parsing without execution."""

    def test_no_args_shows_error_or_help(self) -> None:
        """Invoking without arguments should fail gracefully."""
        result = subprocess.run(
            [sys.executable, "-m", "harness.run_harness"],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT,
        )
        # Without task/tasks, main() will call resolve_task_list which raises HarnessError
        # Exit code 1 expected
        assert result.returncode == 1

    def test_invalid_argument_fails(self) -> None:
        """Invoking with unknown argument should fail."""
        result = subprocess.run(
            [sys.executable, "-m", "harness.run_harness", "--nonexistent-arg"],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT,
        )
        assert result.returncode != 0
        assert "unrecognized arguments" in result.stderr or "error" in result.stderr.lower()

    def test_conflicting_no_flag_parsing(self) -> None:
        """Both --flag and --no-flag should be parseable (last wins)."""
        # This tests argparse behavior - both should parse without error
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "harness.run_harness",
                "--allow-incomplete-diffs",
                "--no-allow-incomplete-diffs",
                "--help",  # Add --help to exit cleanly after parsing
            ],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT,
        )
        assert result.returncode == 0


class TestDryRunMode:
    """Tests for dry-run mode (no network calls, no task execution)."""

    @pytest.fixture
    def available_task(self) -> str:
        """Get an available task ID for testing."""
        task = get_available_task()
        if task is None:
            pytest.skip("No tasks available in tasks/ directory")
        return task

    def test_dry_run_exits_zero(self, available_task: str) -> None:
        """Dry-run with valid task should exit with code 0."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "harness.run_harness",
                "--task",
                available_task,
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"

    def test_dry_run_outputs_prompt(self, available_task: str) -> None:
        """Dry-run should output the prompt for the task."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "harness.run_harness",
                "--task",
                available_task,
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT,
        )
        # Should contain prompt header
        assert "Prompt for" in result.stdout or available_task in result.stdout

    def test_dry_run_with_include_tests(self, available_task: str) -> None:
        """Dry-run with --include-tests should work."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "harness.run_harness",
                "--task",
                available_task,
                "--dry-run",
                "--include-tests",
            ],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"

    def test_dry_run_nonexistent_task_fails(self) -> None:
        """Dry-run with nonexistent task should fail with exit code 1."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "harness.run_harness",
                "--task",
                "nonexistent_task_xyz_12345",
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT,
        )
        assert result.returncode == 1
        # Should mention harness error or task not found
        assert "error" in result.stderr.lower() or "not found" in result.stderr.lower()


class TestModuleInvocation:
    """Tests for module invocation patterns."""

    def test_module_invocation_works(self) -> None:
        """python -m harness.run_harness should work."""
        result = subprocess.run(
            [sys.executable, "-m", "harness.run_harness", "--help"],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT,
        )
        assert result.returncode == 0

    def test_direct_script_invocation_works(self) -> None:
        """Direct script invocation should work with PYTHONPATH set."""
        project_root = Path(__file__).parent.parent
        script_path = project_root / "harness" / "run_harness.py"

        if not script_path.exists():
            pytest.skip("run_harness.py not found")

        # Set PYTHONPATH to project root so imports work
        env = os.environ.copy()
        env["PYTHONPATH"] = str(project_root)

        result = subprocess.run(
            [sys.executable, str(script_path), "--help"],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT,
            cwd=str(project_root),
            env=env,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"


class TestResumeRetryArguments:
    """Tests for resume/retry argument combinations."""

    def test_resume_from_without_dir_fails(self) -> None:
        """--resume-from without valid directory should fail."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "harness.run_harness",
                "--resume-from",
                "/nonexistent/path/to/run",
            ],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT,
        )
        assert result.returncode == 1
        assert "not found" in result.stderr.lower() or "error" in result.stderr.lower()

    def test_retry_api_errors_flag_parses(self) -> None:
        """--retry-api-errors should be parseable."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "harness.run_harness",
                "--retry-api-errors",
                "--help",
            ],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT,
        )
        # Should parse without error (--help exits early)
        assert result.returncode == 0

    def test_resume_incomplete_flag_parses(self) -> None:
        """--resume-incomplete should be parseable."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "harness.run_harness",
                "--resume-incomplete",
                "--help",
            ],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT,
        )
        assert result.returncode == 0


class TestExitCodes:
    """Tests for correct exit codes."""

    def test_help_exits_zero(self) -> None:
        """--help should exit with code 0."""
        result = subprocess.run(
            [sys.executable, "-m", "harness.run_harness", "--help"],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT,
        )
        assert result.returncode == 0

    def test_missing_required_args_exits_nonzero(self) -> None:
        """Missing required arguments should exit with non-zero code."""
        result = subprocess.run(
            [sys.executable, "-m", "harness.run_harness"],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT,
        )
        assert result.returncode != 0

    def test_invalid_task_exits_one(self) -> None:
        """Invalid task should exit with code 1 (HarnessError)."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "harness.run_harness",
                "--task",
                "invalid_task_name_xyz",
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT,
        )
        assert result.returncode == 1


class TestOutputStability:
    """Tests that verify output format stability for regression detection."""

    def test_help_format_stable(self) -> None:
        """--help output format should be stable (no random ordering)."""
        results = []
        for _ in range(3):
            result = subprocess.run(
                [sys.executable, "-m", "harness.run_harness", "--help"],
                capture_output=True,
                text=True,
                timeout=SUBPROCESS_TIMEOUT,
            )
            results.append(result.stdout)

        # All outputs should be identical
        assert all(r == results[0] for r in results), "Help output is not deterministic"

    @pytest.fixture
    def available_task(self) -> str:
        """Get an available task ID for testing."""
        task = get_available_task()
        if task is None:
            pytest.skip("No tasks available in tasks/ directory")
        return task

    def test_dry_run_output_stable(self, available_task: str) -> None:
        """Dry-run output should be deterministic."""
        results = []
        for _ in range(2):
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "harness.run_harness",
                    "--task",
                    available_task,
                    "--dry-run",
                ],
                capture_output=True,
                text=True,
                timeout=SUBPROCESS_TIMEOUT,
            )
            results.append(result.stdout)

        assert results[0] == results[1], "Dry-run output is not deterministic"


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_empty_task_string_fails(self) -> None:
        """Empty task string should fail gracefully."""
        result = subprocess.run(
            [sys.executable, "-m", "harness.run_harness", "--task", ""],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT,
        )
        assert result.returncode != 0

    def test_task_with_special_chars_fails(self) -> None:
        """Task with special characters should fail gracefully (not crash)."""
        result = subprocess.run(
            [sys.executable, "-m", "harness.run_harness", "--task", "../../../etc/passwd"],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT,
        )
        # Should fail but not crash
        assert result.returncode != 0

    def test_negative_samples_value(self) -> None:
        """Negative samples value should be handled gracefully."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "harness.run_harness",
                "--samples",
                "-1",
                "--help",
            ],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT,
        )
        # argparse should allow this (main() clamps to 1), --help exits early
        assert result.returncode == 0

    def test_large_samples_value(self) -> None:
        """Large samples value should parse without overflow."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "harness.run_harness",
                "--samples",
                "1000000",
                "--help",
            ],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT,
        )
        assert result.returncode == 0

    def test_invalid_temperature_type_fails(self) -> None:
        """Non-numeric temperature should fail."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "harness.run_harness",
                "--temperature",
                "not_a_number",
            ],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT,
        )
        assert result.returncode != 0
        assert "error" in result.stderr.lower()

    def test_unicode_in_model_name(self) -> None:
        """Unicode in model name should not crash."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "harness.run_harness",
                "--models",
                "model/with-unicode-\u00e9\u00e0",
                "--help",
            ],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT,
        )
        # Should parse (--help exits early)
        assert result.returncode == 0
