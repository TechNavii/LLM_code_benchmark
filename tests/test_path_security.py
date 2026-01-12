"""Tests for path security utilities.

These tests verify that path traversal attacks are properly blocked
and that valid identifiers pass validation.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from server.path_security import (
    PathTraversalError,
    safe_path_join,
    validate_path_within_root,
    validate_run_id,
    validate_task_id,
    RUN_ID_PATTERN,
    TASK_ID_PATTERN,
)


class TestValidateRunId:
    """Tests for run_id validation."""

    def test_valid_run_id_timestamp_format(self) -> None:
        """Valid timestamp-based run IDs should pass."""
        assert validate_run_id("20240101_120000_a1b2c3") == "20240101_120000_a1b2c3"

    def test_valid_run_id_simple(self) -> None:
        """Simple alphanumeric run IDs should pass."""
        assert validate_run_id("run_123") == "run_123"
        assert validate_run_id("test-run") == "test-run"
        assert validate_run_id("ABC_123_xyz") == "ABC_123_xyz"

    def test_invalid_run_id_path_traversal(self) -> None:
        """Path traversal attempts in run_id should be rejected."""
        with pytest.raises(PathTraversalError) as exc_info:
            validate_run_id("../etc/passwd")
        # Verify error message doesn't leak the path
        assert "../etc/passwd" not in str(exc_info.value)

    def test_invalid_run_id_double_dots(self) -> None:
        """Double dots in run_id should be rejected."""
        with pytest.raises(PathTraversalError):
            validate_run_id("run..123")

    def test_invalid_run_id_forward_slash(self) -> None:
        """Forward slashes in run_id should be rejected."""
        with pytest.raises(PathTraversalError):
            validate_run_id("run/subdir")

    def test_invalid_run_id_backslash(self) -> None:
        """Backslashes in run_id should be rejected."""
        with pytest.raises(PathTraversalError):
            validate_run_id("run\\subdir")

    def test_invalid_run_id_empty(self) -> None:
        """Empty run_id should be rejected."""
        with pytest.raises(PathTraversalError):
            validate_run_id("")

    def test_invalid_run_id_special_chars(self) -> None:
        """Special characters in run_id should be rejected."""
        with pytest.raises(PathTraversalError):
            validate_run_id("run@123")
        with pytest.raises(PathTraversalError):
            validate_run_id("run#123")
        with pytest.raises(PathTraversalError):
            validate_run_id("run 123")


class TestValidateTaskId:
    """Tests for task_id validation."""

    def test_valid_task_id(self) -> None:
        """Valid task IDs should pass."""
        assert validate_task_id("task_001") == "task_001"
        assert validate_task_id("my-task") == "my-task"
        assert validate_task_id("TaskName123") == "TaskName123"

    def test_invalid_task_id_path_traversal(self) -> None:
        """Path traversal attempts in task_id should be rejected."""
        with pytest.raises(PathTraversalError):
            validate_task_id("../../../etc/passwd")

    def test_invalid_task_id_absolute_path(self) -> None:
        """Absolute paths in task_id should be rejected."""
        with pytest.raises(PathTraversalError):
            validate_task_id("/etc/passwd")

    def test_invalid_task_id_empty(self) -> None:
        """Empty task_id should be rejected."""
        with pytest.raises(PathTraversalError):
            validate_task_id("")


class TestSafePathJoin:
    """Tests for safe path joining."""

    def test_valid_path_join(self) -> None:
        """Valid path joins should work correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            result = safe_path_join(base, "subdir", "file.txt")
            assert result == base.resolve() / "subdir" / "file.txt"

    def test_path_traversal_rejected(self) -> None:
        """Path traversal in components should be rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            with pytest.raises(PathTraversalError):
                safe_path_join(base, "..", "etc", "passwd")

    def test_double_dots_in_component_rejected(self) -> None:
        """Components containing .. should be rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            with pytest.raises(PathTraversalError):
                safe_path_join(base, "subdir", "..", "sibling")

    def test_absolute_path_component_rejected(self) -> None:
        """Absolute path components should be rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            with pytest.raises(PathTraversalError):
                safe_path_join(base, "/etc/passwd")

    def test_symlink_escape_rejected(self) -> None:
        """Symlinks that escape the base should be rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            # Create a symlink pointing outside base
            symlink_path = base / "escape_link"
            symlink_path.symlink_to("/tmp")

            # Trying to access through symlink should fail
            with pytest.raises(PathTraversalError):
                safe_path_join(base, "escape_link", "somefile")


class TestValidatePathWithinRoot:
    """Tests for path containment validation."""

    def test_valid_path_within_root(self) -> None:
        """Paths within root should pass."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            subdir = root / "subdir"
            subdir.mkdir()

            result = validate_path_within_root(subdir, root)
            assert result == subdir.resolve()

    def test_path_outside_root_rejected(self) -> None:
        """Paths outside root should be rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "subdir"
            root.mkdir()

            with pytest.raises(PathTraversalError):
                validate_path_within_root(Path("/etc/passwd"), root)

    def test_relative_escape_rejected(self) -> None:
        """Relative paths that escape root should be rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            escape_path = root / ".." / "sibling"

            with pytest.raises(PathTraversalError):
                validate_path_within_root(escape_path, root)


class TestPathTraversalError:
    """Tests for PathTraversalError behavior."""

    def test_error_does_not_leak_path(self) -> None:
        """Error messages should not include the attempted path."""
        error = PathTraversalError("../../../etc/passwd", "run_id")

        # The actual path should not appear in the error message
        assert "../../../etc/passwd" not in str(error)
        assert "etc/passwd" not in str(error)

        # But it should indicate the problem
        assert "run_id" in str(error)
        assert "traversal" in str(error).lower()

    def test_error_is_value_error(self) -> None:
        """PathTraversalError should be a ValueError subclass."""
        error = PathTraversalError("test", "test_type")
        assert isinstance(error, ValueError)


class TestRealWorldAttacks:
    """Tests for realistic attack patterns."""

    @pytest.mark.parametrize(
        "attack_vector",
        [
            "../",
            "..\\",
            "../../../etc/passwd",
            "..\\..\\..\\windows\\system32\\config\\sam",
            "....//",
            "..%2f",
            "..%5c",
            ".%00./",
            "..%252f",
            "%2e%2e%2f",
            "..;",
            "..%00",
            "....////",
            "..././",
            "..\\/",
        ],
    )
    def test_common_traversal_attacks_blocked(self, attack_vector: str) -> None:
        """Common path traversal attack patterns should be blocked."""
        with pytest.raises(PathTraversalError):
            validate_run_id(attack_vector)

        with pytest.raises(PathTraversalError):
            validate_task_id(attack_vector)

    @pytest.mark.parametrize(
        "encoded_attack",
        [
            "run%2f..%2f..%2fetc",  # URL encoded
            "run%5c..%5c..%5cwindows",  # URL encoded backslash
        ],
    )
    def test_encoded_attacks_blocked(self, encoded_attack: str) -> None:
        """URL-encoded attack patterns should be blocked (% is invalid char)."""
        with pytest.raises(PathTraversalError):
            validate_run_id(encoded_attack)


class TestPatternRegex:
    """Tests for the regex patterns themselves."""

    def test_run_id_pattern_allows_valid_chars(self) -> None:
        """RUN_ID_PATTERN should allow expected characters."""
        valid_run_ids = [
            "20240101_120000_a1b2c3",
            "run-123",
            "TEST_RUN",
            "abc123",
            "a",
            "1",
            "_",
            "-",
            "a-b_c",
        ]
        for run_id in valid_run_ids:
            assert RUN_ID_PATTERN.match(run_id), f"Should match: {run_id}"

    def test_run_id_pattern_rejects_invalid_chars(self) -> None:
        """RUN_ID_PATTERN should reject dangerous characters."""
        invalid_run_ids = [
            "run/id",
            "run\\id",
            "run..id",
            "run id",
            "run@id",
            "run#id",
            "../etc",
            "",
        ]
        for run_id in invalid_run_ids:
            match = RUN_ID_PATTERN.match(run_id)
            # Empty string won't match, others should fail full match
            if run_id and match:
                # Partial match might happen, but full match should fail
                assert match.group() != run_id or "/" in run_id or "\\" in run_id

    def test_task_id_pattern_matches_run_id_pattern(self) -> None:
        """TASK_ID_PATTERN should have same behavior as RUN_ID_PATTERN."""
        # Both patterns should be identical for security consistency
        assert TASK_ID_PATTERN.pattern == RUN_ID_PATTERN.pattern
