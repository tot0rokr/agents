"""doctor — run scripts/doctor.sh from the agents repo and return its output."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .. import repo as repo_lib


def doctor(repo_path: str | None = None, timeout: float = 60.0) -> dict:
    """Run the harness `doctor.sh` script and capture its result.

    Args:
        repo_path: Override repo discovery.
        timeout:   Max seconds to wait for doctor.sh.

    Returns a dict with:
        ok (bool):        True iff exit_code is 0.
        exit_code (int):  Process exit code (-1 if repo not found, -2 timeout).
        stdout (str):     Captured stdout (truncated to last 8 KiB).
        stderr (str):     Captured stderr (truncated to last 8 KiB).
        repo (str|None):  Resolved repo path used (None if not found).
    """
    repo_root = repo_lib.find_repo(Path(repo_path) if repo_path else None)
    if repo_root is None:
        return {
            "ok": False,
            "exit_code": -1,
            "stdout": "",
            "stderr": "agents repo not found (set AGENTS_REPO or clone to ~/agents)",
            "repo": None,
        }

    script = repo_root / "scripts" / "doctor.sh"
    if not script.is_file():
        return {
            "ok": False,
            "exit_code": -1,
            "stdout": "",
            "stderr": f"missing script: {script}",
            "repo": str(repo_root),
        }

    try:
        result = subprocess.run(
            ["bash", str(script)],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(repo_root),
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "exit_code": -2,
            "stdout": "",
            "stderr": f"doctor.sh exceeded {timeout}s",
            "repo": str(repo_root),
        }

    return {
        "ok": result.returncode == 0,
        "exit_code": result.returncode,
        "stdout": _tail(result.stdout, 8192),
        "stderr": _tail(result.stderr, 8192),
        "repo": str(repo_root),
    }


def _tail(s: str, max_bytes: int) -> str:
    encoded = s.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return s
    return "...\n" + encoded[-max_bytes:].decode("utf-8", errors="replace")
