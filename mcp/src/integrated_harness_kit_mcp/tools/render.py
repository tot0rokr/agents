"""render — invoke render scripts to regenerate per-tool configs."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .. import repo as repo_lib

_SCRIPTS_FOR_KIND: dict[str, list[str]] = {
    "mcp": ["render-mcp.sh"],
    "commands": ["render-gemini-commands.sh"],
    "all": ["render-mcp.sh", "render-gemini-commands.sh"],
}


def render(
    kind: str = "all",
    repo_path: str | None = None,
    timeout: float = 60.0,
) -> dict:
    """Regenerate per-tool configs from canonical sources.

    Args:
        kind: One of "mcp", "commands", "all". Default "all".
        repo_path: Override repo discovery.
        timeout: Max seconds per script.

    Returns:
        ok (bool):      True iff every requested script exited 0.
        repo (str|None): Resolved repo path.
        scripts (list):  Per-script results, each with name/exit_code/
                         stdout/stderr.
    """
    if kind not in _SCRIPTS_FOR_KIND:
        return {
            "ok": False,
            "repo": None,
            "scripts": [],
            "error": (
                f"unknown kind {kind!r}; expected one of "
                f"{sorted(_SCRIPTS_FOR_KIND)}"
            ),
        }

    repo_root = repo_lib.find_repo(Path(repo_path) if repo_path else None)
    if repo_root is None:
        return {
            "ok": False,
            "repo": None,
            "scripts": [],
            "error": "agents repo not found",
        }

    results: list[dict] = []
    overall_ok = True
    for script_name in _SCRIPTS_FOR_KIND[kind]:
        script = repo_root / "scripts" / script_name
        if not script.is_file():
            results.append(
                {
                    "name": script_name,
                    "exit_code": -1,
                    "stdout": "",
                    "stderr": f"missing script: {script}",
                }
            )
            overall_ok = False
            continue

        try:
            result = subprocess.run(
                ["bash", str(script)],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(repo_root),
            )
        except subprocess.TimeoutExpired:
            results.append(
                {
                    "name": script_name,
                    "exit_code": -2,
                    "stdout": "",
                    "stderr": f"{script_name} exceeded {timeout}s",
                }
            )
            overall_ok = False
            continue

        results.append(
            {
                "name": script_name,
                "exit_code": result.returncode,
                "stdout": _tail(result.stdout, 4096),
                "stderr": _tail(result.stderr, 4096),
            }
        )
        if result.returncode != 0:
            overall_ok = False

    return {
        "ok": overall_ok,
        "repo": str(repo_root),
        "scripts": results,
    }


def _tail(s: str, max_bytes: int) -> str:
    encoded = s.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return s
    return "...\n" + encoded[-max_bytes:].decode("utf-8", errors="replace")
