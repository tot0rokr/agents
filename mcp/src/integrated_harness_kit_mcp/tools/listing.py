"""list_content / list_mcp_servers — what the harness offers, and who supplies it."""

from __future__ import annotations

import json
from pathlib import Path

from .. import layout
from ._common import need_repo

# Fields an MCP server entry may expose. An allowlist, not a denylist: overlay
# servers carry `env` and `headers` with real credentials, and neither the
# model nor the transcript has any business seeing them.
SERVER_FIELDS: tuple[str, ...] = ("url", "transport", "command", "args", "enabled")


def list_content(kind: str, repo_path: str | None = None) -> dict:
    """List skills, commands, subagents, memory or instructions with provenance.

    Args:
        kind: one of skills, commands, subagents, memory, instructions.

    Each entry carries `source`: {"kind": "base"} or
    {"kind": "overlay", "alias": "<alias>"}.
    """
    if kind not in layout.CONTENT_KINDS:
        return {
            "ok": False,
            "error": f"unknown kind {kind!r}; expected one of {sorted(layout.CONTENT_KINDS)}",
        }

    repo_root, fail = need_repo(repo_path)
    if fail:
        return fail

    directory, pattern = layout.CONTENT_KINDS[kind]
    base = repo_root / directory
    if not base.is_dir():
        return {"ok": True, "repo": str(repo_root), "kind": kind, "entries": []}

    entries: list[dict] = []
    if pattern is None:
        candidates = sorted(p for p in base.iterdir() if p.is_dir())
        for child in candidates:
            skill_md = child / "SKILL.md"
            if not skill_md.is_file():
                continue
            rel = str(child.relative_to(repo_root))
            meta = _frontmatter(skill_md)
            entries.append(
                {
                    "name": meta.get("name", child.name),
                    "description": meta.get("description", ""),
                    "path": rel,
                    "source": layout.provenance(repo_root, rel),
                }
            )
    else:
        for md in sorted(base.glob(pattern)):
            rel = str(md.relative_to(repo_root))
            if rel == layout.MEMORY_INDEX or rel in layout.ARTIFACTS:
                continue
            meta = _frontmatter(md)
            entries.append(
                {
                    "name": meta.get("name", md.stem),
                    "description": meta.get("description", ""),
                    "path": rel,
                    "source": layout.provenance(repo_root, rel),
                }
            )

    return {"ok": True, "repo": str(repo_root), "kind": kind, "entries": entries}


def list_mcp_servers(scope: str = "effective", repo_path: str | None = None) -> dict:
    """List MCP servers.

    Args:
        scope: "effective" — what the tools actually get (base plus every
               enabled overlay, i.e. the rendered file);
               "base" — only what this public repo tracks;
               "both" — each set, plus the names only an overlay supplies.

    Credentials are never returned: only the fields in SERVER_FIELDS.
    """
    if scope not in ("effective", "base", "both"):
        return {"ok": False, "error": f"unknown scope {scope!r}"}

    repo_root, fail = need_repo(repo_path)
    if fail:
        return fail

    effective = _servers(repo_root / "shared" / "mcp" / "servers.json")
    base = _servers(repo_root / "shared" / "mcp" / "servers.base.json")
    overlay_only = sorted(set(effective) - set(base))

    payload: dict = {"ok": True, "repo": str(repo_root), "overlay_only": overlay_only}
    if scope in ("effective", "both"):
        payload["effective"] = [_entry(name, cfg) for name, cfg in sorted(effective.items())]
    if scope in ("base", "both"):
        payload["base"] = [_entry(name, cfg) for name, cfg in sorted(base.items())]
    return payload


def _servers(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data.get("servers") or {}


def _entry(name: str, cfg: dict) -> dict:
    entry = {"name": name, "description": cfg.get("description", "")}
    for key in SERVER_FIELDS:
        if cfg.get(key) is not None:
            entry[key] = cfg[key]
    withheld = sorted(k for k in ("env", "headers") if cfg.get(k))
    if withheld:
        entry["withheld"] = withheld
    return entry


def _frontmatter(path: Path) -> dict:
    try:
        text = path.read_text()
    except OSError:
        return {}
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    meta: dict = {}
    for line in text[3:end].splitlines():
        if ":" not in line or line.startswith(" ") or line.startswith("\t"):
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip().strip('"')
    return meta
