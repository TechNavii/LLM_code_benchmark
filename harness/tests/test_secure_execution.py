from __future__ import annotations

from pathlib import Path

from harness.secure_execution import secure_run


def test_secure_run_handles_nonexistent_command(tmp_path: Path) -> None:
    result = secure_run(["/usr/bin/env", "false"], workspace_path=tmp_path)
    assert result.returncode != 0


def test_secure_run_limits(tmp_path: Path) -> None:
    script = tmp_path / "loop.sh"
    script.write_text("#!/bin/sh\nwhile true; do :; done\n", encoding="utf-8")
    script.chmod(0o755)

    result = secure_run([str(script)], workspace_path=tmp_path, timeout=1)
    assert result.returncode != 0
