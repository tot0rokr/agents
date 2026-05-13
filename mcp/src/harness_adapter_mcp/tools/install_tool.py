"""install — invoke scripts/install.py against the discovered repo.

We subprocess `python3 scripts/install.py` instead of importing it
in-process. Two reasons: install.py uses `Path(__file__)` to find its
own repo root, so importing it from elsewhere can confuse that lookup;
and subprocess isolation makes the MCP server immune to any partial
state install.py might leave in the interpreter if a rollback fails.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from .. import repo as repo_lib


def install(
    repo_path: str | None = None,
    home: str | None = None,
    dry_run: bool = False,
    timeout: float = 300.0,
) -> dict:
    """Run the harness installer.

    Args:
        repo_path: Override repo discovery. Defaults to `$AGENTS_REPO` or
                   `~/agents`.
        home:      Override `$HOME` for the install. Useful for testing.
        dry_run:   If True, pass `--dry-run` to install.py and make no
                   changes.
        timeout:   Max seconds to wait for the installer.

    Returns:
        ok (bool):        True iff the installer exited 0.
        exit_code (int):  Process exit code (-1 repo missing, -2 timeout).
        repo (str|None):  Resolved repo path used.
        stdout, stderr:   Captured output (tail-truncated to 8 KiB each).
    """
    repo_root = repo_lib.find_repo(Path(repo_path) if repo_path else None)
    if repo_root is None:
        return {
            "ok": False,
            "exit_code": -1,
            "repo": None,
            "stdout": "",
            "stderr": (
                "agents repo not found. Call `clone` first or set "
                "AGENTS_REPO."
            ),
        }

    script = repo_root / "scripts" / "install.py"
    if not script.is_file():
        return {
            "ok": False,
            "exit_code": -1,
            "repo": str(repo_root),
            "stdout": "",
            "stderr": f"missing script: {script}",
        }

    cmd = [sys.executable, str(script)]
    if dry_run:
        cmd.append("--dry-run")
    if home:
        cmd.extend(["--home", str(home)])
    cmd.extend(["--repo", str(repo_root)])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "exit_code": -2,
            "repo": str(repo_root),
            "stdout": "",
            "stderr": f"install.py exceeded {timeout}s",
        }

    return {
        "ok": result.returncode == 0,
        "exit_code": result.returncode,
        "repo": str(repo_root),
        "stdout": _tail(result.stdout, 8192),
        "stderr": _tail(result.stderr, 8192),
    }


def _tail(s: str, max_bytes: int) -> str:
    encoded = s.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return s
    return "...\n" + encoded[-max_bytes:].decode("utf-8", errors="replace")
