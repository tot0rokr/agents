"""mcp_server_set / mcp_server_remove — manage MCP server definitions.

Writes go to a tracked source (`shared/mcp/servers.base.json`) or to an
overlay's fragment, never to the rendered `servers.json`, which the next render
would overwrite. Credentials (`env`, `headers`) are accepted only for an
overlay target, because the base repo is public.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .. import layout, repo_scripts
from ._common import need_repo

BASE_REL = "shared/mcp/servers.base.json"
OVERLAY_FRAGMENT = "mcp/servers.json"

# Server names become keys in JSON, TOML section headers and shell-adjacent
# config, so keep them to what every renderer can represent.
_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")


def mcp_server_set(
    name: str,
    url: str | None = None,
    command: str | None = None,
    args: list[str] | None = None,
    transport: str | None = None,
    description: str = "",
    env: dict | None = None,
    headers: dict | None = None,
    enabled: bool | None = None,
    target: str = "base",
    repo_path: str | None = None,
) -> dict:
    """Add or update one MCP server, then re-render.

    Args:
        url: remote server; `transport` defaults to "http".
        command/args: local stdio server.
        env/headers: accepted only when target is an overlay.
        target: "base" or "overlay:<alias>".
    """
    repo_root, fail = need_repo(repo_path)
    if fail:
        return fail
    if not _NAME_RE.match(name or ""):
        return {
            "ok": False,
            "error": f"invalid server name {name!r}; use letters, digits, dot, dash or underscore",
        }
    if bool(url) == bool(command):
        return {"ok": False, "error": "give exactly one of url or command"}

    path, alias, problem = _target_path(repo_root, target)
    if problem:
        return problem
    if (env or headers) and alias is None:
        return {
            "ok": False,
            "error": "env/headers hold credentials and the base repo is public; use an overlay target",
        }

    entry: dict = {}
    if description:
        entry["description"] = description
    if url:
        entry["url"] = url
        entry["transport"] = transport or "http"
    else:
        entry["command"] = command
        entry["args"] = args or []
    if env:
        entry["env"] = env
    if headers:
        entry["headers"] = headers
    if enabled is not None:
        entry["enabled"] = enabled

    data = layout.read_json(path) if path.is_file() else {}
    servers = data.setdefault("servers", {})
    existed = name in servers
    servers[name] = entry
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    except OSError as exc:
        return {"ok": False, "error": f"cannot write {path}: {exc}"}

    return {
        "ok": True,
        "repo": str(repo_root),
        "name": name,
        "action": "updated" if existed else "added",
        "target": target,
        "wrote": str(path.relative_to(repo_root)),
        "secrets_written": sorted(k for k in ("env", "headers") if entry.get(k)),
        "render": _render(repo_root),
    }


def mcp_server_remove(name: str, target: str = "base", repo_path: str | None = None) -> dict:
    """Remove a server from the base or an overlay, then re-render."""
    repo_root, fail = need_repo(repo_path)
    if fail:
        return fail

    path, _, problem = _target_path(repo_root, target)
    if problem:
        return problem

    data = layout.read_json(path) if path.is_file() else {}
    servers = data.get("servers") or {}
    if name not in servers:
        return {
            "ok": False,
            "error": f"{name} is not defined in {path.name}",
            "defined_here": sorted(servers),
        }
    servers.pop(name)
    data["servers"] = servers
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")

    return {
        "ok": True,
        "repo": str(repo_root),
        "removed": name,
        "target": target,
        "render": _render(repo_root),
    }


def _target_path(repo_root: Path, target: str) -> tuple[Path, str | None, dict | None]:
    if target == "base":
        return repo_root / BASE_REL, None, None
    if not target.startswith("overlay:"):
        return Path(), None, {"ok": False, "error": f"unknown target {target!r}"}
    alias = target.split(":", 1)[1]
    known = {entry.get("alias") for entry in layout.registered_overlays(repo_root)}
    if alias not in known:
        return Path(), None, {"ok": False, "error": f"no overlay registered as {alias!r}"}
    return layout.overlay_root(repo_root, alias) / OVERLAY_FRAGMENT, alias, None


def _render(repo_root: Path) -> dict:
    module = repo_scripts.load(repo_root, "render_settings")
    if module is None or not hasattr(module, "render_mcp"):
        return {"ok": False, "error": "repo has no render_settings.render_mcp()"}
    try:
        with repo_scripts.scripts_on_path(repo_root):
            module.render_mcp(repo_root)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return {"ok": True, "written": "shared/mcp/servers.json"}
