"""Where every file in the harness comes from, and what may be done to it.

The harness has three kinds of file and they have to be told apart before
anything writes, stages or renders:

    base source     tracked, hand-edited, public          -> write, commit
    artifact        untracked, produced by a render       -> render only
    overlay-owned   a symlink into overlays/<alias>/      -> the overlay's repo

Every tool asks this module rather than carrying its own path list, because
the last time those lists were duplicated they drifted apart.
"""

from __future__ import annotations

import json
from pathlib import Path

OVERLAYS_DIR = "overlays"
REGISTRY_REL = "overlays/registry.local.json"
APPLIED_REL = "overlays/applied.local.json"

# artifact -> the tracked source it is rendered from
ARTIFACTS: dict[str, str] = {
    "claude/settings.json": "claude/settings.base.json",
    "shared/mcp/servers.json": "shared/mcp/servers.base.json",
    "shared/memory/MEMORY.md": "shared/memory/MEMORY.base.md",
}

# Rendered per-tool configs that this repo still tracks. They must only ever
# receive base content — see `render`.
PUBLIC_RENDERED: tuple[str, ...] = (
    "codex/config.toml",
    "opencode/opencode.json",
    "gemini/settings.json",
    "gemini/commands/",
)

# (directory, glob or None for directory entries)
CONTENT_KINDS: dict[str, tuple[str, str | None]] = {
    "skills": ("universal/skills", None),
    "commands": ("shared/commands", "*.md"),
    "subagents": ("shared/subagents", "*.md"),
    "memory": ("shared/memory", "*.md"),
    "instructions": ("shared/instructions", "*.md"),
}

# Where an overlay keeps each kind, relative to the overlay root.
OVERLAY_KINDS: dict[str, str] = {
    "skills": "skills",
    "commands": "commands",
    "subagents": "subagents",
    "memory": "memory",
    "instructions": "instructions",
}

CREDENTIAL_MARKERS: tuple[str, ...] = (
    ".pypirc",
    "auth.json",
    ".credentials.json",
    "secrets/",
    ".env",
)

BUILD_MARKERS: tuple[str, ...] = ("mcp/dist/", "mcp/build/", ".egg-info")

# Files the memory index is built from; never a drop-in.
MEMORY_INDEX = "shared/memory/MEMORY.md"
MEMORY_INDEX_FRAGMENT = "memory/MEMORY.md"


def normalize(rel_path: str) -> str:
    """Repo-relative form. Not `lstrip("./")` — that eats the dot of `.pypirc`."""
    rel = str(rel_path)
    while rel.startswith("./"):
        rel = rel[2:]
    return rel.lstrip("/")


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def applied_links(repo_root: Path) -> dict[str, str]:
    """Repo-relative path -> owning overlay alias, from the applied record."""
    data = read_json(repo_root / APPLIED_REL)
    return {item["link"]: item["alias"] for item in data.get("links", []) if "link" in item}


def registered_overlays(repo_root: Path) -> list[dict]:
    data = read_json(repo_root / REGISTRY_REL)
    entries = data.get("overlays", [])
    return sorted(entries, key=lambda e: (e.get("priority", 50), e.get("alias", "")))


def overlay_root(repo_root: Path, alias: str) -> Path:
    return repo_root / OVERLAYS_DIR / alias


def supports_overlays(repo_root: Path) -> bool:
    return (repo_root / "scripts" / "overlay.py").is_file()


def classify(repo_root: Path, rel_path: str) -> str:
    """One of: artifact, base_source, overlay_owned, credential, build_artifact, runtime, other."""
    rel = normalize(rel_path)

    if any(marker in rel for marker in CREDENTIAL_MARKERS):
        return "credential"
    if any(marker in rel for marker in BUILD_MARKERS):
        return "build_artifact"
    if rel in ARTIFACTS or any(rel.startswith(p) for p in PUBLIC_RENDERED):
        return "artifact"
    if rel.startswith(OVERLAYS_DIR + "/"):
        return "overlay_owned"
    if rel in applied_links(repo_root):
        return "overlay_owned"

    path = repo_root / rel
    if path.is_symlink():
        target = path.resolve()
        overlays = (repo_root / OVERLAYS_DIR).resolve()
        if str(target).startswith(str(overlays)):
            return "overlay_owned"

    if rel in ARTIFACTS.values():
        return "base_source"
    for directory, _ in CONTENT_KINDS.values():
        if rel.startswith(directory + "/"):
            return "base_source"
    if rel.startswith("scripts/") or rel.startswith("mcp/src/") or rel in ("shared/AGENTS.md",):
        return "base_source"
    if rel.startswith("claude/") or rel.startswith("codex/") or rel.startswith("gemini/"):
        return "runtime"
    return "other"


def provenance(repo_root: Path, rel_path: str) -> dict:
    """Who supplies this path: the base repo, or one of the overlays."""
    alias = applied_links(repo_root).get(normalize(rel_path))
    if alias:
        return {"kind": "overlay", "alias": alias}

    path = repo_root / rel_path
    if path.is_symlink():
        target = path.resolve()
        overlays = (repo_root / OVERLAYS_DIR).resolve()
        if str(target).startswith(str(overlays) + "/"):
            alias = Path(str(target)[len(str(overlays)) + 1 :]).parts[0]
            return {"kind": "overlay", "alias": alias}
    return {"kind": "base"}


def writable(repo_root: Path, rel_path: str) -> tuple[bool, str]:
    """May a tool write this path directly? Returns (ok, reason)."""
    kind = classify(repo_root, rel_path)
    if kind == "artifact":
        source = ARTIFACTS.get(normalize(rel_path))
        hint = f" — edit {source} and re-render" if source else " — produced by a render"
        return False, f"{rel_path} is a render artifact{hint}"
    if kind == "overlay_owned":
        alias = provenance(repo_root, rel_path).get("alias", "an overlay")
        return False, f"{rel_path} is provided by overlay '{alias}'; write it there instead"
    if kind == "credential":
        return False, f"{rel_path} looks like a credential file"
    if kind == "build_artifact":
        return False, f"{rel_path} is a build artifact"
    return True, ""
