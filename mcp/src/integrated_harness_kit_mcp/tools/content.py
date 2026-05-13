"""Add/remove content in the agents harness — skills, MCP servers, commands, sub-agents.

Each `add_*` writes the canonical file (and re-runs the matching render
script when the content needs propagation). Each `remove_*` is the inverse.
Both refuse silently-overwriting moves — `add_*` rejects an existing
name, `remove_*` rejects a missing one — so the caller always knows
exactly what changed.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from .. import repo as repo_lib

_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")


def _validate_name(name: str) -> str | None:
    """Return an error message if `name` is not a safe identifier, else None."""
    if not name:
        return "name must not be empty"
    if not _NAME_RE.match(name):
        return (
            "name must be 1-64 chars, start with alphanumeric, and contain only "
            "letters, digits, dot, hyphen, underscore"
        )
    return None


def _need_repo(repo_path: str | None) -> tuple[Path | None, dict | None]:
    repo_root = repo_lib.find_repo(Path(repo_path) if repo_path else None)
    if repo_root is None:
        return None, {"ok": False, "error": "agents repo not found"}
    return repo_root, None


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------


def add_skill(
    name: str,
    description: str,
    body: str,
    repo_path: str | None = None,
) -> dict:
    """Create `universal/skills/<name>/SKILL.md` with the given frontmatter + body.

    All four CLI agents auto-discover the new skill at next launch. No render
    step needed.

    Refuses to overwrite an existing skill of the same name.
    """
    err = _validate_name(name)
    if err:
        return {"ok": False, "error": err}
    if not description.strip():
        return {"ok": False, "error": "description must not be empty"}

    repo_root, fail = _need_repo(repo_path)
    if fail:
        return fail

    skill_dir = repo_root / "universal" / "skills" / name
    skill_md = skill_dir / "SKILL.md"
    if skill_md.exists():
        return {"ok": False, "error": f"skill already exists: {skill_md}"}

    skill_dir.mkdir(parents=True, exist_ok=False)
    skill_md.write_text(
        f"---\nname: {name}\ndescription: {description.strip()}\n---\n\n{body.rstrip()}\n"
    )
    return {"ok": True, "path": str(skill_md)}


def remove_skill(name: str, repo_path: str | None = None) -> dict:
    """Delete `universal/skills/<name>/` entirely. Refuses if not present."""
    err = _validate_name(name)
    if err:
        return {"ok": False, "error": err}

    repo_root, fail = _need_repo(repo_path)
    if fail:
        return fail

    skill_dir = repo_root / "universal" / "skills" / name
    if not skill_dir.is_dir():
        return {"ok": False, "error": f"skill not found: {skill_dir}"}

    shutil.rmtree(skill_dir)
    return {"ok": True, "removed": str(skill_dir)}


# ---------------------------------------------------------------------------
# MCP servers
# ---------------------------------------------------------------------------


def add_mcp_server(
    name: str,
    description: str = "",
    url: str | None = None,
    transport: str | None = None,
    command: str | None = None,
    args: list[str] | None = None,
    env: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    repo_path: str | None = None,
) -> dict:
    """Add an MCP server to `shared/mcp/servers.json` and re-render per-tool configs.

    Provide either `url` (remote HTTP/SSE) or `command` (local stdio).
    `transport` only applies to remote servers — defaults to `http`; pass
    `sse` for Server-Sent Events.
    """
    err = _validate_name(name)
    if err:
        return {"ok": False, "error": err}

    if bool(url) == bool(command):
        return {
            "ok": False,
            "error": "exactly one of `url` (remote) or `command` (stdio) is required",
        }

    repo_root, fail = _need_repo(repo_path)
    if fail:
        return fail

    servers_json = repo_root / "shared" / "mcp" / "servers.json"
    if servers_json.exists():
        data = json.loads(servers_json.read_text())
    else:
        data = {"servers": {}}
    data.setdefault("servers", {})

    if name in data["servers"]:
        return {"ok": False, "error": f"MCP server already exists: {name}"}

    entry: dict = {}
    if description.strip():
        entry["description"] = description.strip()
    if url:
        entry["url"] = url
        entry["transport"] = transport or "http"
        if headers:
            entry["headers"] = headers
    else:
        entry["command"] = command
        if args:
            entry["args"] = list(args)
        if env:
            entry["env"] = dict(env)

    data["servers"][name] = entry
    servers_json.write_text(json.dumps(data, indent=2) + "\n")

    render_result = _run_render(repo_root, "render-mcp.sh")
    return {"ok": render_result["ok"], "name": name, "render": render_result}


def remove_mcp_server(name: str, repo_path: str | None = None) -> dict:
    """Remove an MCP server from `shared/mcp/servers.json` and re-render."""
    err = _validate_name(name)
    if err:
        return {"ok": False, "error": err}

    repo_root, fail = _need_repo(repo_path)
    if fail:
        return fail

    servers_json = repo_root / "shared" / "mcp" / "servers.json"
    if not servers_json.exists():
        return {"ok": False, "error": "shared/mcp/servers.json does not exist"}

    data = json.loads(servers_json.read_text())
    servers = data.get("servers") or {}
    if name not in servers:
        return {"ok": False, "error": f"MCP server not found: {name}"}

    del servers[name]
    data["servers"] = servers
    servers_json.write_text(json.dumps(data, indent=2) + "\n")

    render_result = _run_render(repo_root, "render-mcp.sh")
    return {"ok": render_result["ok"], "removed": name, "render": render_result}


# ---------------------------------------------------------------------------
# Slash commands
# ---------------------------------------------------------------------------


def add_command(
    name: str,
    description: str,
    body: str,
    repo_path: str | None = None,
) -> dict:
    """Create `shared/commands/<name>.md` and re-render Gemini TOML output."""
    err = _validate_name(name)
    if err:
        return {"ok": False, "error": err}
    if not description.strip():
        return {"ok": False, "error": "description must not be empty"}

    repo_root, fail = _need_repo(repo_path)
    if fail:
        return fail

    md = repo_root / "shared" / "commands" / f"{name}.md"
    if md.exists():
        return {"ok": False, "error": f"command already exists: {md}"}

    md.parent.mkdir(parents=True, exist_ok=True)
    md.write_text(f"---\ndescription: {description.strip()}\n---\n\n{body.rstrip()}\n")

    render_result = _run_render(repo_root, "render-gemini-commands.sh")
    return {"ok": render_result["ok"], "path": str(md), "render": render_result}


def remove_command(name: str, repo_path: str | None = None) -> dict:
    """Delete `shared/commands/<name>.md` and re-render Gemini TOML output."""
    err = _validate_name(name)
    if err:
        return {"ok": False, "error": err}

    repo_root, fail = _need_repo(repo_path)
    if fail:
        return fail

    md = repo_root / "shared" / "commands" / f"{name}.md"
    if not md.exists():
        return {"ok": False, "error": f"command not found: {md}"}

    md.unlink()
    render_result = _run_render(repo_root, "render-gemini-commands.sh")
    return {"ok": render_result["ok"], "removed": str(md), "render": render_result}


# ---------------------------------------------------------------------------
# Sub-agents
# ---------------------------------------------------------------------------


def add_subagent(
    name: str,
    description: str,
    body: str,
    repo_path: str | None = None,
) -> dict:
    """Create `shared/subagents/<name>.md`. Claude + OpenCode auto-discover."""
    err = _validate_name(name)
    if err:
        return {"ok": False, "error": err}
    if not description.strip():
        return {"ok": False, "error": "description must not be empty"}

    repo_root, fail = _need_repo(repo_path)
    if fail:
        return fail

    md = repo_root / "shared" / "subagents" / f"{name}.md"
    if md.exists():
        return {"ok": False, "error": f"sub-agent already exists: {md}"}

    md.parent.mkdir(parents=True, exist_ok=True)
    md.write_text(
        f"---\nname: {name}\ndescription: {description.strip()}\n---\n\n{body.rstrip()}\n"
    )
    return {"ok": True, "path": str(md)}


def remove_subagent(name: str, repo_path: str | None = None) -> dict:
    """Delete `shared/subagents/<name>.md`."""
    err = _validate_name(name)
    if err:
        return {"ok": False, "error": err}

    repo_root, fail = _need_repo(repo_path)
    if fail:
        return fail

    md = repo_root / "shared" / "subagents" / f"{name}.md"
    if not md.exists():
        return {"ok": False, "error": f"sub-agent not found: {md}"}

    md.unlink()
    return {"ok": True, "removed": str(md)}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _run_render(repo_root: Path, script_name: str, timeout: float = 60.0) -> dict:
    """Run a render script and capture its result. Best-effort if missing."""
    script = repo_root / "scripts" / script_name
    if not script.is_file():
        return {
            "ok": False,
            "script": script_name,
            "exit_code": -1,
            "stderr": f"missing script: {script}",
        }
    try:
        result = subprocess.run(
            ["bash", str(script)],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(repo_root),
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "script": script_name,
            "exit_code": -2,
            "stderr": f"{script_name} exceeded {timeout}s",
        }

    return {
        "ok": result.returncode == 0,
        "script": script_name,
        "exit_code": result.returncode,
        "stdout": result.stdout[-2048:],
        "stderr": result.stderr[-2048:],
    }
