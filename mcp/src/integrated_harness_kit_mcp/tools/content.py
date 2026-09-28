"""scaffold / remove_content — create and delete harness content.

One pair of tools instead of eight `add_*`/`remove_*`, because the four kinds
differed only in which directory they wrote to. What they gain over the caller
writing the file itself is the part that is easy to get wrong: choosing between
the base repo and an overlay, refusing a name another overlay already supplies,
and re-linking or re-rendering afterwards.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .. import layout
from ._common import need_repo

_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")


def scaffold(
    kind: str,
    name: str,
    description: str = "",
    body: str = "",
    target: str = "base",
    repo_path: str | None = None,
) -> dict:
    """Create a skill, command, subagent, memory or instruction file.

    Args:
        kind: skills | commands | subagents | memory | instructions
        name: file or directory name, without extension.
        target: "base" for this repo, or "overlay:<alias>" for a private
                overlay. Environment-specific content belongs in an overlay —
                the base repo is public.

    An overlay target also adds the memory index line (for `kind="memory"`)
    and re-applies the overlay so the file is linked into place.
    """
    repo_root, fail = need_repo(repo_path)
    if fail:
        return fail
    problem = _validate(kind, name)
    if problem:
        return problem

    alias, problem = _target_alias(repo_root, target)
    if problem:
        return problem

    effective_rel = _effective_rel(kind, name)
    existing = repo_root / effective_rel
    if existing.exists() or existing.is_symlink():
        return {
            "ok": False,
            "error": f"{effective_rel} already exists",
            "source": layout.provenance(repo_root, effective_rel),
        }

    if alias:
        path = _overlay_path(repo_root, alias, kind, name)
    else:
        _, pattern = layout.CONTENT_KINDS[kind]
        # A skill is a directory with SKILL.md inside; everything else is a file.
        path = repo_root / effective_rel / "SKILL.md" if pattern is None else repo_root / effective_rel

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_template(kind, name, description, body))

    result = {
        "ok": True,
        "kind": kind,
        "name": name,
        "path": str(path.relative_to(repo_root)),
        "target": f"overlay:{alias}" if alias else "base",
    }

    if alias and kind == "memory":
        result["index"] = _add_index_line(repo_root, alias, name, description)
    if alias:
        result["apply"] = _apply_overlay(repo_root, alias)
    return result


def remove_content(kind: str, name: str, repo_path: str | None = None) -> dict:
    """Delete content. Refuses anything an overlay owns — remove it there."""
    repo_root, fail = need_repo(repo_path)
    if fail:
        return fail
    problem = _validate(kind, name)
    if problem:
        return problem

    rel = _effective_rel(kind, name)
    path = repo_root / rel
    if not path.exists() and not path.is_symlink():
        return {"ok": False, "error": f"{rel} not found"}

    allowed, reason = layout.writable(repo_root, rel)
    if not allowed:
        return {"ok": False, "error": reason, "source": layout.provenance(repo_root, rel)}

    if path.is_dir() and not path.is_symlink():
        for child in sorted(path.rglob("*"), reverse=True):
            child.rmdir() if child.is_dir() else child.unlink()
        path.rmdir()
    else:
        path.unlink()
    return {"ok": True, "kind": kind, "removed": rel}


def _validate(kind: str, name: str) -> dict | None:
    if kind not in layout.CONTENT_KINDS:
        return {
            "ok": False,
            "error": f"unknown kind {kind!r}; expected one of {sorted(layout.CONTENT_KINDS)}",
        }
    if not _NAME_RE.match(name):
        return {"ok": False, "error": f"invalid name {name!r}"}
    return None


def _target_alias(repo_root: Path, target: str) -> tuple[str | None, dict | None]:
    if target == "base":
        return None, None
    if not target.startswith("overlay:"):
        return None, {"ok": False, "error": f"unknown target {target!r}"}
    alias = target.split(":", 1)[1]
    known = {entry.get("alias") for entry in layout.registered_overlays(repo_root)}
    if alias not in known:
        return None, {
            "ok": False,
            "error": f"no overlay registered as {alias!r}",
            "registered": sorted(a for a in known if a),
        }
    return alias, None


def _effective_rel(kind: str, name: str) -> str:
    directory, pattern = layout.CONTENT_KINDS[kind]
    return f"{directory}/{name}" if pattern is None else f"{directory}/{name}.md"


def _overlay_path(repo_root: Path, alias: str, kind: str, name: str) -> Path:
    sub = layout.OVERLAY_KINDS[kind]
    root = layout.overlay_root(repo_root, alias) / sub
    _, pattern = layout.CONTENT_KINDS[kind]
    return root / name / "SKILL.md" if pattern is None else root / f"{name}.md"


def _template(kind: str, name: str, description: str, body: str) -> str:
    body = body.rstrip() or "TODO"
    if kind == "skills":
        return f"---\nname: {name}\ndescription: {description.strip()}\n---\n\n{body}\n"
    if kind == "commands":
        return f"---\ndescription: {description.strip()}\n---\n\n{body}\n"
    if kind == "subagents":
        return f"---\nname: {name}\ndescription: {description.strip()}\n---\n\n{body}\n"
    if kind == "memory":
        return (
            f"---\nname: {name}\ndescription: {description.strip()}\n"
            f"metadata:\n  node_type: memory\n  type: project\n---\n\n{body}\n"
        )
    return f"# {name}\n\n{body}\n"


def _add_index_line(repo_root: Path, alias: str, name: str, description: str) -> dict:
    fragment = layout.overlay_root(repo_root, alias) / layout.MEMORY_INDEX_FRAGMENT
    line = f"- [{name}]({name}.md) — {description.strip()}"
    try:
        existing = fragment.read_text() if fragment.is_file() else ""
        if line in existing:
            return {"ok": True, "added": False, "path": str(fragment)}
        fragment.parent.mkdir(parents=True, exist_ok=True)
        prefix = "" if not existing or existing.endswith("\n") else "\n"
        fragment.write_text(existing + prefix + line + "\n")
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "added": True, "path": str(fragment.relative_to(repo_root))}


def _apply_overlay(repo_root: Path, alias: str) -> dict:
    script = repo_root / "scripts" / "overlay.py"
    if not script.is_file():
        return {"ok": False, "error": "this repo has no scripts/overlay.py"}
    try:
        proc = subprocess.run(
            ["python3", str(script), "install", alias],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=60.0,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": proc.returncode == 0,
        "stdout": proc.stdout[-2048:],
        "stderr": proc.stderr[-2048:],
    }
