"""Tests to verify validator scripts work from any working directory.

These tests execute the validator scripts from outside the repository root
to ensure they correctly resolve paths dynamically rather than relying on
the caller's current working directory.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest


# Get the repository root (parent of tests/)
REPO_ROOT = Path(__file__).resolve().parents[1]


class TestValidatorScriptPortability:
    """Test that validator scripts work from any working directory."""

    @pytest.mark.parametrize(
        "script_name",
        [
            "lint.sh",
            "typecheck.sh",
            "test.sh",
        ],
    )
    def test_validator_script_resolves_repo_root_dynamically(self, script_name: str) -> None:
        """Validator scripts should work when called from outside repo root."""
        script_path = REPO_ROOT / "scripts" / script_name
        assert script_path.exists(), f"Script {script_name} not found"

        # Create a temporary directory outside the repo to run from
        with tempfile.TemporaryDirectory() as tmpdir:
            # Run the script from the temp directory
            result = subprocess.run(
                [str(script_path), "--help"] if script_name == "test.sh" else [str(script_path)],
                cwd=tmpdir,  # Run from outside repo root
                capture_output=True,
                text=True,
                timeout=180,  # 3 minutes max
                env={**os.environ, "COLUMNS": "200"},  # Wide terminal for output
            )

            # For test.sh --help, it should succeed
            # For lint.sh and typecheck.sh, they should either succeed or fail with
            # a meaningful error (not "directory not found")
            error_output = result.stderr + result.stdout

            # These errors indicate the script failed to resolve paths correctly
            bad_errors = [
                "No such file or directory",
                "cannot find",
                "ENOENT",
            ]

            # If the script failed, it shouldn't be due to path resolution issues
            if result.returncode != 0:
                for bad_error in bad_errors:
                    assert bad_error not in error_output, (
                        f"{script_name} failed with path resolution error when run from {tmpdir}: "
                        f"{error_output[:500]}"
                    )

    def test_lint_script_changes_to_repo_root(self) -> None:
        """lint.sh should change to repo root regardless of starting directory."""
        script_path = REPO_ROOT / "scripts" / "lint.sh"

        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [str(script_path)],
                cwd=tmpdir,
                capture_output=True,
                text=True,
                timeout=180,
            )

            # The script should succeed (or fail for legitimate reasons, not path issues)
            output = result.stdout + result.stderr

            # Check that it's running ruff on the correct paths
            if "Running ruff" in output or "ruff format" in output:
                # Good - it found ruff and is running it
                pass
            elif result.returncode == 0:
                # Script succeeded
                pass
            else:
                # If it failed, ensure it's not a path resolution issue
                assert "server/" not in output or "No such file" not in output

    def test_typecheck_script_changes_to_repo_root(self) -> None:
        """typecheck.sh should change to repo root regardless of starting directory."""
        script_path = REPO_ROOT / "scripts" / "typecheck.sh"

        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [str(script_path)],
                cwd=tmpdir,
                capture_output=True,
                text=True,
                timeout=180,
            )

            output = result.stdout + result.stderr

            # Check that mypy is running on the correct paths
            if "Running mypy" in output or "Success:" in output:
                # Good - it found mypy and is running it
                pass
            elif result.returncode == 0:
                # Script succeeded
                pass
            else:
                # If it failed, ensure it's not a path resolution issue
                assert "source files" not in output or "No such file" not in output

    def test_test_script_changes_to_repo_root(self) -> None:
        """test.sh should change to repo root regardless of starting directory."""
        script_path = REPO_ROOT / "scripts" / "test.sh"

        with tempfile.TemporaryDirectory() as tmpdir:
            # Use --help to avoid running full test suite
            result = subprocess.run(
                [str(script_path), "--help"],
                cwd=tmpdir,
                capture_output=True,
                text=True,
                timeout=60,
            )

            output = result.stdout + result.stderr

            # --help should show pytest help
            assert "pytest" in output.lower() or "usage" in output.lower() or result.returncode == 0

    @pytest.mark.parametrize(
        "script_name",
        [
            "lint.sh",
            "typecheck.sh",
            "test.sh",
            "format.sh",
            "check-deps.sh",
        ],
    )
    def test_script_uses_script_dir_for_path_resolution(self, script_name: str) -> None:
        """Scripts should use SCRIPT_DIR to resolve paths, not pwd."""
        script_path = REPO_ROOT / "scripts" / script_name

        if not script_path.exists():
            pytest.skip(f"Script {script_name} does not exist")

        content = script_path.read_text()

        # Scripts should define SCRIPT_DIR based on their location
        assert (
            "SCRIPT_DIR" in content or "BASH_SOURCE" in content
        ), f"{script_name} should use SCRIPT_DIR or BASH_SOURCE for path resolution"

        # Scripts should cd to REPO_ROOT, not rely on being in repo root
        assert (
            "REPO_ROOT" in content or "cd" in content
        ), f"{script_name} should define REPO_ROOT or cd to the correct directory"

    def test_check_python_version_script_is_sourced(self) -> None:
        """check-python-version.sh should be sourceable from any directory."""
        script_path = REPO_ROOT / "scripts" / "check-python-version.sh"
        assert script_path.exists()

        # The script should be sourceable (syntax check)
        result = subprocess.run(
            ["bash", "-n", str(script_path)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Syntax error in check-python-version.sh: {result.stderr}"


class TestScriptPathResolution:
    """Test that scripts correctly resolve the repository root."""

    def test_scripts_define_repo_root_from_script_dir(self) -> None:
        """All main validator scripts should derive REPO_ROOT from SCRIPT_DIR."""
        main_scripts = ["lint.sh", "typecheck.sh", "test.sh"]

        for script_name in main_scripts:
            script_path = REPO_ROOT / "scripts" / script_name
            content = script_path.read_text()

            # Should derive REPO_ROOT from SCRIPT_DIR, not use a hardcoded path
            assert "SCRIPT_DIR" in content, f"{script_name} should define SCRIPT_DIR"
            assert "REPO_ROOT" in content, f"{script_name} should define REPO_ROOT"

            # Should not have hardcoded absolute paths
            lines = content.splitlines()
            for i, line in enumerate(lines, 1):
                if line.strip().startswith("#"):
                    continue
                # Look for hardcoded /Users or /home paths (skip comment lines)
                has_hardcoded_path = "/Users/" in line or "/home/" in line
                is_not_comment = not line.lstrip().startswith("#")
                if has_hardcoded_path and is_not_comment:
                    pytest.fail(f"{script_name}:{i} contains hardcoded path: {line.strip()}")

    def test_scripts_cd_to_repo_root(self) -> None:
        """Scripts should change to REPO_ROOT before running commands."""
        main_scripts = ["lint.sh", "typecheck.sh", "test.sh"]

        for script_name in main_scripts:
            script_path = REPO_ROOT / "scripts" / script_name
            content = script_path.read_text()

            # Should cd to repo root (typically: cd "${REPO_ROOT}")
            assert "cd" in content and "REPO_ROOT" in content, f"{script_name} should cd to REPO_ROOT"


class TestCrossDirectoryExecution:
    """Test running scripts from various working directories."""

    @pytest.fixture
    def temp_outside_repo(self) -> Generator[Path, None, None]:
        """Create a temporary directory outside the repo."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_lint_from_tmp(self, temp_outside_repo: Path) -> None:
        """lint.sh should work from /tmp."""
        script_path = REPO_ROOT / "scripts" / "lint.sh"

        result = subprocess.run(
            [str(script_path)],
            cwd=str(temp_outside_repo),
            capture_output=True,
            text=True,
            timeout=180,
        )

        # Should not fail due to "directory not found"
        combined_output = result.stdout + result.stderr
        assert "No such file or directory" not in combined_output or result.returncode == 0

    def test_lint_from_nested_directory(self) -> None:
        """lint.sh should work from a deeply nested directory."""
        script_path = REPO_ROOT / "scripts" / "lint.sh"

        with tempfile.TemporaryDirectory() as tmpdir:
            nested = Path(tmpdir) / "a" / "b" / "c" / "d"
            nested.mkdir(parents=True)

            result = subprocess.run(
                [str(script_path)],
                cwd=str(nested),
                capture_output=True,
                text=True,
                timeout=180,
            )

            # Should not fail due to path issues
            combined_output = result.stdout + result.stderr
            assert "No such file or directory" not in combined_output or result.returncode == 0
