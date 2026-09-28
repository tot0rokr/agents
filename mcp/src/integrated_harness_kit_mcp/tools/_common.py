"""Shared plumbing for the tool modules."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .. import repo as repo_lib


def need_repo(repo_path: str | None) -> tuple[Path | None, dict | None]:
    """Resolve the repo, or return the error payload every tool returns."""
    repo_root = repo_lib.find_repo(Path(repo_path) if repo_path else None)
    if repo_root is None:
        return None, {"ok": False, "repo": None, "error": "agents repo not found"}
    return repo_root, None


def run(
    cmd: list[str],
    cwd: Path,
    timeout: float = 60.0,
    env: dict[str, str] | None = None,
) -> dict:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "exit_code": -2,
            "stdout": "",
            "stderr": f"command timed out after {timeout}s: {' '.join(cmd)}",
        }
    except OSError as exc:
        return {"ok": False, "exit_code": -1, "stdout": "", "stderr": str(exc)}
    return {
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "stdout": proc.stdout[-4096:],
        "stderr": proc.stderr[-4096:],
    }


def git(args: list[str], cwd: Path, timeout: float = 30.0) -> dict:
    return run(["git", *args], cwd=cwd, timeout=timeout)


def identity_error(result: dict, cwd: Path) -> str | None:
    """Turn git's identity complaint into something a caller can act on."""
    stderr = result.get("stderr", "")
    if "Author identity unknown" in stderr or "Please tell me who you are" in stderr:
        return (
            f"git has no author identity for {cwd}. Set it per-repo — "
            "git -C <repo> config user.name / user.email — choosing the identity "
            "that matches the remote's domain."
        )
    return None
