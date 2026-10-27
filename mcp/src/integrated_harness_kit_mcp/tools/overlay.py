"""overlay_* — drive the repo's own scripts/overlay.py.

The overlay mechanism lives in the harness repo, not here: an overlay declares
what it owns, `overlay.py` links it in and renders, and this module is a thin,
structured front for that so an agent can do the same from a chat.
"""

from __future__ import annotations

import fnmatch
import subprocess
from pathlib import Path, PurePosixPath

from .. import layout
from ._common import git, identity_error, need_repo


def overlay_list(repo_path: str | None = None) -> dict:
    """Registered overlays, their priority, and how many links each supplies."""
    repo_root, fail = need_repo(repo_path)
    if fail:
        return fail
    if not layout.supports_overlays(repo_root):
        return {"ok": False, "repo": str(repo_root), "error": "this repo has no scripts/overlay.py"}

    applied = layout.applied_links(repo_root)
    counts: dict[str, int] = {}
    for alias in applied.values():
        counts[alias] = counts.get(alias, 0) + 1

    entries = []
    for entry in layout.registered_overlays(repo_root):
        alias = entry.get("alias", "")
        root = layout.overlay_root(repo_root, alias)
        entries.append(
            {
                "alias": alias,
                "priority": entry.get("priority", 50),
                "enabled": entry.get("enabled", True),
                "url": entry.get("url", ""),
                "ref": entry.get("ref", ""),
                "cloned": (root / "overlay.json").is_file(),
                "links": counts.get(alias, 0),
                "dirty": _dirty(root),
            }
        )
    return {"ok": True, "repo": str(repo_root), "overlays": entries}


def overlay_route(path: str | None = None, repo_path: str | None = None) -> dict:
    """Which overlay owns a piece of work — for session logs, journals, records."""
    repo_root, fail = need_repo(repo_path)
    if fail:
        return fail
    args = ["route"]
    if path:
        args.append(path)
    result = _script(repo_root, args + ["--explain"])
    if not result["ok"]:
        return result
    explained = result["stdout"].strip()
    alias = _script(repo_root, args)["stdout"].strip()
    return {"ok": True, "repo": str(repo_root), "alias": alias, "explain": explained}


def overlay_install(alias: str | None = None, repo_path: str | None = None) -> dict:
    """Apply one overlay (or every enabled one) and re-render."""
    repo_root, fail = need_repo(repo_path)
    if fail:
        return fail
    return {
        "repo": str(repo_root),
        **_script(repo_root, ["install"] + ([alias] if alias else [])),
    }


def overlay_add(
    alias: str,
    url: str | None = None,
    priority: int | None = None,
    ref: str = "main",
    repo_path: str | None = None,
) -> dict:
    """Register an overlay, cloning it when `overlays/<alias>` is not there yet.

    `priority` defaults to the overlay manifest's own value.
    """
    repo_root, fail = need_repo(repo_path)
    if fail:
        return fail
    args = ["add", alias] + ([url] if url else []) + ["--ref", ref]
    if priority is not None:
        args += ["--priority", str(priority)]
    return {"repo": str(repo_root), **_script(repo_root, args)}


def overlay_remove(alias: str, purge: bool = False, repo_path: str | None = None) -> dict:
    """Unlink an overlay and re-render. `purge` also deletes the clone."""
    repo_root, fail = need_repo(repo_path)
    if fail:
        return fail
    args = ["remove", alias] + (["--purge"] if purge else [])
    return {"repo": str(repo_root), **_script(repo_root, args)}


def overlay_setup(
    alias: str | None = None,
    yes: bool = False,
    repo_path: str | None = None,
) -> dict:
    """Environment setup steps an overlay declares.

    Defaults to a dry run: these steps execute shell commands and agents from
    the overlay, so nothing runs until `yes=True` is passed deliberately.
    """
    repo_root, fail = need_repo(repo_path)
    if fail:
        return fail
    args = ["setup"] + ([alias] if alias else []) + (["--yes"] if yes else ["--dry-run"])
    result = _script(repo_root, args, timeout=900.0 if yes else 120.0)
    return {"repo": str(repo_root), "executed": yes, **result}


def overlay_commit(
    alias: str,
    message: str,
    paths: list[str] | None = None,
    repo_path: str | None = None,
) -> dict:
    """Commit inside an overlay's own repo.

    `audit_drift` reports overlays as dirty; this is how that gets resolved
    without leaving the chat. Paths are relative to the overlay root and may
    not escape it. Machine-only *.local.json / *.local.toml files are refused
    even when the overlay's .gitignore lets them through.
    """
    repo_root, fail = need_repo(repo_path)
    if fail:
        return fail
    if not message.strip():
        return {"ok": False, "error": "commit message must not be empty"}

    root = layout.overlay_root(repo_root, alias)
    if not (root / "overlay.json").is_file():
        return {"ok": False, "error": f"{alias} is not a cloned overlay"}

    selected = paths or ["-A"]
    for entry in selected:
        if entry == "-A":
            continue
        resolved = (root / entry).resolve()
        if not str(resolved).startswith(str(root.resolve())):
            return {"ok": False, "error": f"path escapes the overlay: {entry}"}

    staged = git(["add", *selected], cwd=root)
    if not staged["ok"]:
        return {"ok": False, "step": "add", **staged}

    local = _staged_local_files(root)
    if local is None:
        return {"ok": False, "step": "diff", "error": "cannot list what is staged in the overlay"}
    if local:
        return _refuse_local(root, alias, local)

    status = git(["diff", "--cached", "--name-only"], cwd=root)
    if not status["stdout"].strip():
        return {"ok": False, "error": "nothing staged in the overlay"}

    committed = git(["commit", "-m", message], cwd=root)
    head = git(["log", "-1", "--format=%h %s"], cwd=root)
    payload = {
        "ok": committed["ok"],
        "alias": alias,
        "files": status["stdout"].split(),
        "head": head["stdout"].strip(),
        "commit": committed,
    }
    identity = identity_error(committed, root)
    if identity:
        payload["error"] = identity
    return payload


def _staged_local_files(root: Path) -> list[str] | None:
    """Machine-only files the index would add to, or change in, the overlay's git.

    The overlay's .gitignore is what normally keeps them out, but one written
    before a pattern existed (*.local.toml came after *.local.json) or by hand
    lets `git add -A` sweep them in, and a file committed before its pattern
    was added is tracked, so ignoring no longer applies. Staged deletions
    pass: untracking one is the cure. None when git cannot say.

    The patterns are matched here, on each file's name as .gitignore does,
    not handed to git as a pathspec: GIT_GLOB_PATHSPECS or
    GIT_LITERAL_PATHSPECS in the server's environment would change what such a
    pathspec matches and let the file through. Not through `git()` either,
    whose output is cut to its last 4 KiB: a long list would lose its head.
    """
    try:
        listed = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--no-renames", "--diff-filter=d", "-z"],
            cwd=str(root), capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if listed.returncode != 0:
        return None
    return [
        path for path in listed.stdout.split("\0")
        if path and any(fnmatch.fnmatchcase(PurePosixPath(path).name, pat) for pat in layout.OVERLAY_LOCAL_PATTERNS)
    ]


def _refuse_local(root: Path, alias: str, local: list[str]) -> dict:
    """Take machine-only files back out of the index and say how to fix it.

    Unstaged rather than left in place, or the next plain `git commit` in
    the overlay would still carry them.
    """
    unstaged = git(["reset", "-q", "--", *local], cwd=root)
    patterns = " and ".join(f"'{pattern}'" for pattern in layout.OVERLAY_LOCAL_PATTERNS)
    payload = {
        "ok": False,
        "alias": alias,
        "refused": local,
        "error": (
            f"refusing to commit machine-only {', '.join(local)}: add {patterns} to "
            f"overlays/{alias}/.gitignore (and 'git rm --cached' any already tracked), "
            "then commit again"
        ),
    }
    if not unstaged["ok"]:
        payload["unstage"] = unstaged
    return payload


def _script(repo_root: Path, args: list[str], timeout: float = 120.0) -> dict:
    script = repo_root / "scripts" / "overlay.py"
    if not script.is_file():
        return {"ok": False, "error": "this repo has no scripts/overlay.py"}
    try:
        proc = subprocess.run(
            ["python3", str(script), *args],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "stdout": proc.stdout[-4096:],
        "stderr": proc.stderr[-4096:],
    }


def _dirty(root: Path) -> bool | None:
    if not (root / ".git").exists():
        return None
    result = git(["status", "--porcelain"], cwd=root)
    return bool(result["stdout"].strip()) if result["ok"] else None
