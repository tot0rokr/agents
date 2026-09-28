"""update / audit_drift / commit — keep an installed harness fresh and clean.

`audit_drift` and `commit` classify every path through `layout`, so they know
the three kinds of file the overlay split created: tracked sources that may be
committed, render artifacts that may not, and overlay-owned symlinks that
belong to a different repository entirely.
"""

from __future__ import annotations

import re
from pathlib import Path

from .. import layout
from ._common import git, need_repo, run
from .overlay import overlay_install
from .render import render as _render

_PATH_RE = re.compile(r"^[\w./-]+$")

REFUSED_CATEGORIES = ("artifact", "overlay_owned", "credential", "build_artifact")


def update(
    repo_path: str | None = None,
    with_pull: bool = True,
    with_overlays: bool = True,
    timeout: float = 120.0,
) -> dict:
    """Pull, re-render the artifacts, re-apply overlays, then run doctor.

    The per-tool renders are deliberately not part of this: they write files
    this repo tracks, and on a machine with overlays that needs the base-only
    path in `render(scope="public")`.
    """
    repo_root, fail = need_repo(repo_path)
    if fail:
        return fail

    steps: list[dict] = []

    if with_pull:
        result = git(["pull", "--ff-only"], cwd=repo_root, timeout=timeout)
        steps.append({"step": "git pull --ff-only", **result})
        if not result["ok"]:
            return {"ok": False, "repo": str(repo_root), "steps": steps}

    result = _render(scope="artifacts", repo_path=str(repo_root))
    steps.append({"step": "render artifacts", **result})
    if not result.get("ok"):
        return {"ok": False, "repo": str(repo_root), "steps": steps}

    if with_overlays and layout.supports_overlays(repo_root):
        if layout.registered_overlays(repo_root):
            steps.append({"step": "overlay install", **overlay_install(repo_path=str(repo_root))})

    doctor = repo_root / "scripts" / "doctor.sh"
    if doctor.is_file():
        steps.append({"step": "doctor.sh", **run(["bash", str(doctor)], repo_root, timeout)})
    else:
        steps.append({"step": "doctor.sh", "ok": False, "stderr": "missing script"})

    return {
        "ok": all(step.get("ok", False) for step in steps),
        "repo": str(repo_root),
        "steps": steps,
    }


def audit_drift(repo_path: str | None = None) -> dict:
    """Classify every uncommitted change — in this repo and in each overlay.

    Categories come from `layout.classify`: base_source, artifact,
    overlay_owned, credential, build_artifact, runtime, other. Only
    base_source and other are candidates for `commit`.
    """
    repo_root, fail = need_repo(repo_path)
    if fail:
        return fail

    result = git(["status", "--porcelain"], cwd=repo_root, timeout=30.0)
    if not result["ok"]:
        return {"ok": False, "repo": str(repo_root), "error": "git status failed", **result}

    entries: list[dict] = []
    for line in result["stdout"].splitlines():
        if not line.strip():
            continue
        code, path = line[:2].strip() or "??", line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        category = layout.classify(repo_root, path)
        entry = {"code": code, "path": path, "category": category}
        if category == "overlay_owned":
            entry["source"] = layout.provenance(repo_root, path)
        entries.append(entry)

    summary: dict[str, int] = {}
    for entry in entries:
        summary[entry["category"]] = summary.get(entry["category"], 0) + 1

    return {
        "ok": True,
        "repo": str(repo_root),
        "entries": entries,
        "summary": summary,
        "committable": [e["path"] for e in entries if e["category"] in ("base_source", "other")],
        "overlays": _overlay_drift(repo_root),
    }


def commit(
    paths: list[str],
    message: str,
    repo_path: str | None = None,
) -> dict:
    """Stage the listed paths and commit them. Never `git add -A`.

    Refuses render artifacts, overlay-owned symlinks, credentials and build
    output — an overlay's files are committed with `overlay_commit`.
    """
    if not message.strip():
        return {"ok": False, "error": "commit message must not be empty"}
    if not paths:
        return {"ok": False, "error": "must list at least one path"}

    repo_root, fail = need_repo(repo_path)
    if fail:
        return fail

    refused: list[dict] = []
    allowed: list[str] = []
    for path in paths:
        if not _PATH_RE.match(path):
            refused.append({"path": path, "reason": "invalid path"})
            continue
        if not (repo_root / path).exists() and not (repo_root / path).is_symlink():
            refused.append({"path": path, "reason": "does not exist"})
            continue
        category = layout.classify(repo_root, path)
        if category in REFUSED_CATEGORIES:
            entry = {"path": path, "reason": category}
            if category == "overlay_owned":
                alias = layout.provenance(repo_root, path).get("alias")
                entry["hint"] = f"use overlay_commit(alias={alias!r}, ...)"
            refused.append(entry)
            continue
        allowed.append(path)

    if refused:
        return {"ok": False, "repo": str(repo_root), "refused": refused, "staged": []}

    staged = git(["add", "--", *allowed], cwd=repo_root)
    if not staged["ok"]:
        return {"ok": False, "repo": str(repo_root), "step": "add", **staged}

    check = git(["diff", "--cached", "--name-only"], cwd=repo_root)
    if not check["stdout"].strip():
        return {"ok": False, "repo": str(repo_root), "error": "nothing staged"}

    committed = git(["commit", "-m", message], cwd=repo_root)
    head = git(["log", "-1", "--format=%h %s"], cwd=repo_root)
    return {
        "ok": committed["ok"],
        "repo": str(repo_root),
        "staged": check["stdout"].split(),
        "head": head["stdout"].strip(),
        "commit": committed,
    }


def _overlay_drift(repo_root: Path) -> list[dict]:
    out = []
    for entry in layout.registered_overlays(repo_root):
        alias = entry.get("alias", "")
        root = layout.overlay_root(repo_root, alias)
        if not (root / ".git").exists():
            continue
        result = git(["status", "--porcelain"], cwd=root)
        changes = [line for line in result["stdout"].splitlines() if line.strip()]
        if changes:
            out.append(
                {
                    "alias": alias,
                    "path": str(root.relative_to(repo_root)),
                    "changes": changes,
                    "hint": f"overlay_commit(alias={alias!r}, message=...)",
                }
            )
    return out
