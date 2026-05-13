"""list_* — read-only enumerations of what's registered in the harness.

All listing functions follow the same shape: they accept an optional
`repo_path` override, return a list of dicts, and return an empty list
if the repo isn't found. None of them raise.
"""

from __future__ import annotations

import json
from pathlib import Path

from .. import repo as repo_lib


def list_skills(repo_path: str | None = None) -> list[dict]:
    """Return the SKILL.md entries registered under `universal/skills/`.

    Each entry: { name, description, path }.
    """
    repo_root = repo_lib.find_repo(Path(repo_path) if repo_path else None)
    if repo_root is None:
        return []
    skills_dir = repo_root / "universal" / "skills"
    out: list[dict] = []
    for child in sorted(_dirs(skills_dir)):
        skill_md = child / "SKILL.md"
        if not skill_md.is_file():
            continue
        meta = _parse_frontmatter(skill_md.read_text())
        out.append(
            {
                "name": child.name,
                "description": meta.get("description", ""),
                "path": str(skill_md),
            }
        )
    return out


def list_mcp_servers(repo_path: str | None = None) -> list[dict]:
    """Return the MCP servers declared in `shared/mcp/servers.json`.

    Each entry: { name, description, url?, command?, transport? }.
    """
    repo_root = repo_lib.find_repo(Path(repo_path) if repo_path else None)
    if repo_root is None:
        return []
    servers_json = repo_root / "shared" / "mcp" / "servers.json"
    if not servers_json.is_file():
        return []
    try:
        data = json.loads(servers_json.read_text())
    except json.JSONDecodeError:
        return []
    out: list[dict] = []
    for name, cfg in (data.get("servers") or {}).items():
        entry: dict = {
            "name": name,
            "description": cfg.get("description", ""),
        }
        for key in ("url", "transport", "command", "args"):
            if cfg.get(key) is not None:
                entry[key] = cfg[key]
        out.append(entry)
    return out


def list_commands(repo_path: str | None = None) -> list[dict]:
    """Return the slash commands under `shared/commands/`.

    Each entry: { name, description, path }.
    """
    repo_root = repo_lib.find_repo(Path(repo_path) if repo_path else None)
    if repo_root is None:
        return []
    commands_dir = repo_root / "shared" / "commands"
    if not commands_dir.is_dir():
        return []
    out: list[dict] = []
    for md in sorted(commands_dir.glob("*.md")):
        meta = _parse_frontmatter(md.read_text())
        out.append(
            {
                "name": md.stem,
                "description": meta.get("description", ""),
                "path": str(md),
            }
        )
    return out


def list_subagents(repo_path: str | None = None) -> list[dict]:
    """Return the sub-agents under `shared/subagents/`.

    Each entry: { name, description, path }.
    """
    repo_root = repo_lib.find_repo(Path(repo_path) if repo_path else None)
    if repo_root is None:
        return []
    sub_dir = repo_root / "shared" / "subagents"
    if not sub_dir.is_dir():
        return []
    out: list[dict] = []
    for md in sorted(sub_dir.glob("*.md")):
        meta = _parse_frontmatter(md.read_text())
        out.append(
            {
                "name": meta.get("name", md.stem),
                "description": meta.get("description", ""),
                "path": str(md),
            }
        )
    return out


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _dirs(path: Path):
    if not path.is_dir():
        return []
    return [p for p in path.iterdir() if p.is_dir()]


def _parse_frontmatter(text: str) -> dict:
    """Parse a small YAML-ish frontmatter block. Best-effort, no external dep."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 4)
    if end == -1:
        return {}
    block = text[4:end]
    out: dict = {}
    for line in block.splitlines():
        if ":" not in line or line.lstrip().startswith("#"):
            continue
        k, _, v = line.partition(":")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out
