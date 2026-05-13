"""harness_status — inspect the current state of the agents harness."""

from __future__ import annotations

import os
from pathlib import Path

from .. import repo as repo_lib

# Mirror scripts/install.py:LINK_PATHS so the MCP doesn't drift from the
# installer's notion of what should be linked. (Single source of truth would
# be nicer; we'll unify in v0.3 when install logic is fully importable.)
_LINK_PATHS = [
    (".claude", "claude"),
    (".codex", "codex"),
    (".config/opencode", "opencode"),
    (".gemini", "gemini"),
    (".agents", "universal"),
]


def harness_status(
    home: str | None = None,
    repo_path: str | None = None,
) -> dict:
    """Inspect the agents harness on this machine.

    Args:
        home: Override `$HOME` for testing. Defaults to the real home dir.
        repo_path: Override repo discovery. Defaults to env/`~/agents`.

    Returns a dict with keys:
        installed (bool):  True iff all 5 home-dir symlinks resolve correctly.
        repo (str|None):   Absolute path to the agents repo, or None if absent.
        home (str):        The home dir we inspected.
        links (list):      One entry per expected link with state + actual target.
    """
    home_path = Path(home) if home else Path.home()
    repo_root = repo_lib.find_repo(Path(repo_path) if repo_path else None)

    links: list[dict] = []
    for home_rel, repo_rel in _LINK_PATHS:
        target = home_path / home_rel
        entry: dict = {"path": str(target), "expected_repo_sub": repo_rel}
        if target.is_symlink():
            actual = Path(os.readlink(target))
            expected = (repo_root / repo_rel).resolve() if repo_root else None
            if expected is not None and actual == expected:
                entry["state"] = "linked"
                entry["target"] = str(actual)
            else:
                entry["state"] = "linked-elsewhere"
                entry["target"] = str(actual)
        elif target.exists():
            entry["state"] = "real-dir"
        else:
            entry["state"] = "missing"
        links.append(entry)

    installed = repo_root is not None and all(l["state"] == "linked" for l in links)

    return {
        "installed": installed,
        "repo": str(repo_root) if repo_root else None,
        "home": str(home_path),
        "links": links,
    }
