"""Secure subprocess execution utilities for the harness."""

from __future__ import annotations

import resource
import subprocess
from pathlib import Path
from typing import Iterable, Optional


def _resolve_command(command: Iterable[str]) -> list[str]:
    resolved: list[str] = []
    for part in command:
        part_path = Path(part)
        if part_path.exists():
            resolved.append(str(part_path.resolve()))
        else:
            resolved.append(part)
    return resolved


def secure_run(
    command: Iterable[str],
    *,
    workspace_path: Path,
    timeout: int = 300,
    max_memory_mb: int = 512,
    env: Optional[dict[str, str]] = None,
    cwd: Optional[Path] = None,
) -> subprocess.CompletedProcess:
    """Execute a subprocess with basic resource limits and sanitisation."""

    workspace_path = workspace_path.resolve()
    resolved_command = _resolve_command(command)

    def set_limits() -> None:
        memory_bytes = max_memory_mb * 1024 * 1024
        try:
            resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
        except (ValueError, OSError):
            pass
        try:
            resource.setrlimit(resource.RLIMIT_CPU, (timeout, timeout + 1))
        except (ValueError, OSError):
            pass

    process_env = env.copy() if env else None

    try:
        result = subprocess.run(
            resolved_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str((cwd or workspace_path).resolve()),
            timeout=timeout,
            check=False,
            env=process_env,
            preexec_fn=set_limits,
        )
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            args=exc.cmd,
            returncode=-1,
            stdout=exc.output or b"",
            stderr=exc.stderr or b"timeout",
        )

    return result
