"""Locate the tot0rokr/agents repo on this machine."""

from __future__ import annotations

import os
from pathlib import Path


# Marker that confirms a directory is actually the agents repo (and not, say,
# a similarly-named random directory).
_REPO_MARKER = Path("scripts") / "install.py"


def find_repo(repo_path: Path | None = None) -> Path | None:
    """Return the resolved path to the agents repo, or None.

    Resolution rules:
      - If `repo_path` is given, that path is checked **without** any
        fallback. Returns None if it isn't a valid repo. This makes tests
        deterministic and prevents accidental leak of the developer's
        real `~/agents` into a test environment.
      - Otherwise, try `$AGENTS_REPO`, then `~/agents`.

    A candidate is accepted only if it is a directory containing
    `scripts/install.py` (the marker file).
    """
    if repo_path is not None:
        candidate = Path(repo_path)
        return candidate.resolve() if _is_repo(candidate) else None

    env_var = os.environ.get("AGENTS_REPO")
    if env_var:
        candidate = Path(env_var)
        if _is_repo(candidate):
            return candidate.resolve()

    default = Path.home() / "agents"
    if _is_repo(default):
        return default.resolve()

    return None


def _is_repo(path: Path) -> bool:
    return path.is_dir() and (path / _REPO_MARKER).is_file()
