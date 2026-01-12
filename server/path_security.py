"""Path security utilities to prevent path traversal attacks.

This module provides functions to validate and sanitize user-controlled
identifiers before using them in filesystem paths.

SECURITY NOTE: Always use these functions when constructing paths from
user-controlled input (run_id, task_id, filenames, etc.).
"""

from __future__ import annotations

import re
from pathlib import Path


# Pattern for valid run IDs (timestamp_hex format, e.g., "20240101_120000_a1b2c3")
# Also allows legacy formats and UUIDs
RUN_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_\-]+$")

# Pattern for valid task IDs (alphanumeric with underscores/hyphens)
TASK_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_\-]+$")


class PathTraversalError(ValueError):
    """Raised when a path traversal attempt is detected."""

    def __init__(self, identifier: str, identifier_type: str = "identifier") -> None:
        # SECURITY: Never include the actual identifier in error messages
        # to avoid leaking filesystem structure information
        super().__init__(f"Invalid {identifier_type}: path traversal not allowed")
        self.identifier_type = identifier_type


def validate_identifier(
    identifier: str,
    pattern: re.Pattern[str],
    identifier_type: str = "identifier",
) -> str:
    """Validate an identifier against a pattern.

    Args:
        identifier: The identifier to validate
        pattern: Regex pattern the identifier must match
        identifier_type: Type name for error messages (e.g., "run_id", "task_id")

    Returns:
        The validated identifier (unchanged if valid)

    Raises:
        PathTraversalError: If the identifier contains invalid characters
    """
    if not identifier:
        raise PathTraversalError(identifier, identifier_type)

    if not pattern.match(identifier):
        raise PathTraversalError(identifier, identifier_type)

    # Additional checks for path traversal attempts
    if ".." in identifier or "/" in identifier or "\\" in identifier:
        raise PathTraversalError(identifier, identifier_type)

    return identifier


def validate_run_id(run_id: str) -> str:
    """Validate a run ID for safe use in filesystem paths.

    Args:
        run_id: The run ID to validate

    Returns:
        The validated run ID

    Raises:
        PathTraversalError: If the run ID is invalid or contains traversal patterns
    """
    return validate_identifier(run_id, RUN_ID_PATTERN, "run_id")


def validate_task_id(task_id: str) -> str:
    """Validate a task ID for safe use in filesystem paths.

    Args:
        task_id: The task ID to validate

    Returns:
        The validated task ID

    Raises:
        PathTraversalError: If the task ID is invalid or contains traversal patterns
    """
    return validate_identifier(task_id, TASK_ID_PATTERN, "task_id")


def safe_path_join(base: Path, *parts: str, resolve: bool = True) -> Path:
    """Safely join path components, ensuring the result stays within base.

    Args:
        base: The base directory that must contain the result
        *parts: Path components to join (will be validated)
        resolve: Whether to resolve the final path (default True)

    Returns:
        The joined path, guaranteed to be within base

    Raises:
        PathTraversalError: If the resulting path would escape the base directory
    """
    # Start with resolved base
    base_resolved = base.resolve()

    # Join parts one at a time
    result = base_resolved
    for part in parts:
        # Check each component for traversal patterns
        if ".." in part or part.startswith("/") or part.startswith("\\"):
            raise PathTraversalError(part, "path component")

        result = result / part

    # Resolve the final path if requested
    if resolve:
        result = result.resolve()

    # Verify the result is still within base
    try:
        result.relative_to(base_resolved)
    except ValueError:
        # Path escaped the base directory
        raise PathTraversalError("", "path") from None

    return result


def validate_path_within_root(path: Path, root: Path) -> Path:
    """Validate that a path is within a root directory.

    Args:
        path: The path to validate
        root: The root directory that must contain path

    Returns:
        The resolved path, guaranteed to be within root

    Raises:
        PathTraversalError: If the path is outside the root directory
    """
    resolved_path = path.resolve()
    resolved_root = root.resolve()

    try:
        resolved_path.relative_to(resolved_root)
    except ValueError:
        raise PathTraversalError("", "path") from None

    return resolved_path
