"""clone — git clone the agents repo to a target directory."""

from __future__ import annotations

import subprocess
from pathlib import Path

DEFAULT_REPO_URL = "https://github.com/tot0rokr/agents.git"
DEFAULT_DEST = "~/agents"


def clone(
    dest: str = DEFAULT_DEST,
    repo_url: str = DEFAULT_REPO_URL,
    timeout: float = 120.0,
) -> dict:
    """Clone the agents repo to `dest`.

    Args:
        dest:     Filesystem path to clone into. `~` is expanded.
        repo_url: Git URL. Defaults to the canonical upstream.
        timeout:  Seconds to wait before giving up.

    Returns a dict with:
        ok (bool):        True if the clone succeeded.
        exit_code (int):  Process exit code (-1 on validation error,
                          -2 on timeout).
        dest (str):       Resolved absolute target path.
        stdout, stderr:   Captured output (tail-truncated).
    """
    dest_path = Path(dest).expanduser()

    if dest_path.exists():
        return {
            "ok": False,
            "exit_code": -1,
            "dest": str(dest_path),
            "stdout": "",
            "stderr": f"refusing to clone: {dest_path} already exists",
        }

    if not dest_path.parent.is_dir():
        return {
            "ok": False,
            "exit_code": -1,
            "dest": str(dest_path),
            "stdout": "",
            "stderr": f"parent directory does not exist: {dest_path.parent}",
        }

    try:
        result = subprocess.run(
            ["git", "clone", repo_url, str(dest_path)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return {
            "ok": False,
            "exit_code": -1,
            "dest": str(dest_path),
            "stdout": "",
            "stderr": "git is not installed on this machine",
        }
    except subprocess.TimeoutExpired:
        # Clean up any partial clone; clone target was created mid-run.
        if dest_path.exists():
            _rmtree_quiet(dest_path)
        return {
            "ok": False,
            "exit_code": -2,
            "dest": str(dest_path),
            "stdout": "",
            "stderr": f"git clone exceeded {timeout}s",
        }

    if result.returncode != 0 and dest_path.exists():
        _rmtree_quiet(dest_path)

    return {
        "ok": result.returncode == 0,
        "exit_code": result.returncode,
        "dest": str(dest_path),
        "stdout": _tail(result.stdout, 4096),
        "stderr": _tail(result.stderr, 4096),
    }


def _tail(s: str, max_bytes: int) -> str:
    encoded = s.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return s
    return "...\n" + encoded[-max_bytes:].decode("utf-8", errors="replace")


def _rmtree_quiet(p: Path) -> None:
    import shutil
    shutil.rmtree(p, ignore_errors=True)
