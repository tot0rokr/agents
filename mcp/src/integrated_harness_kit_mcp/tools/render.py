"""render — regenerate the harness's derived files, without leaking overlays.

Three scopes, because the outputs have different audiences:

    artifacts  settings.json, servers.json, MEMORY.md   untracked, base+overlays
    public     codex/opencode/gemini configs            tracked here, base only
    local      ~/.claude.json                           this machine, base+overlays

The split exists because the per-tool configs are tracked in a public repo while
`servers.json` now merges private overlays into it. Rendering those files from
the merged source would commit an employer's internal servers, so `public`
renders from `servers.base.json` and `local` carries the merged set.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from .. import layout, repo_scripts
from ._common import need_repo, run

SCOPES = ("artifacts", "public", "local", "all")

SERVERS_REL = "shared/mcp/servers.json"
SERVERS_BASE_REL = "shared/mcp/servers.base.json"


def render(
    scope: str = "artifacts",
    repo_path: str | None = None,
    timeout: float = 60.0,
    home: str | None = None,
) -> dict:
    """Regenerate derived files for one scope (see module docstring)."""
    if scope not in SCOPES:
        return {"ok": False, "error": f"unknown scope {scope!r}; expected one of {list(SCOPES)}"}

    repo_root, fail = need_repo(repo_path)
    if fail:
        return fail

    steps: list[dict] = []
    ok = True

    if scope in ("artifacts", "all"):
        step = _render_artifacts(repo_root)
        steps.append(step)
        ok = ok and step["ok"]

    if scope in ("public", "all"):
        step = _render_public(repo_root, timeout)
        steps.append(step)
        ok = ok and step["ok"]

    if scope in ("local", "all"):
        step = _render_local(repo_root, Path(home).expanduser() if home else Path.home())
        steps.append(step)
        ok = ok and step["ok"]

    return {"ok": ok, "repo": str(repo_root), "scope": scope, "steps": steps}


def _render_artifacts(repo_root: Path) -> dict:
    module = repo_scripts.load(repo_root, "render_settings")
    if module is None or not hasattr(module, "render_all"):
        return {
            "step": "artifacts",
            "ok": False,
            "error": "this repo has no scripts/render_settings.py with render_all()",
        }
    try:
        with repo_scripts.scripts_on_path(repo_root):
            rendered = module.render_all(repo_root)
    except Exception as exc:  # noqa: BLE001 — a bad base file must not kill the server
        return {"step": "artifacts", "ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return {
        "step": "artifacts",
        "ok": True,
        "written": [rel for rel, value in rendered.items() if value],
    }


def _render_public(repo_root: Path, timeout: float) -> dict:
    """Run the shell renderers against base-only servers, then restore."""
    servers = repo_root / SERVERS_REL
    base = repo_root / SERVERS_BASE_REL
    scripts = repo_root / "scripts"

    overlay_only = _overlay_only_servers(repo_root)
    swapped = False
    backup: str | None = None

    if overlay_only and base.is_file():
        backup = servers.read_text() if servers.is_file() else None
        shutil.copyfile(base, servers)
        swapped = True

    results = []
    try:
        for name in ("render-mcp.sh", "render-gemini-commands.sh"):
            script = scripts / name
            if not script.is_file():
                results.append({"script": name, "ok": False, "stderr": "missing script"})
                continue
            results.append({"script": name, **run(["bash", str(script)], repo_root, timeout)})
    finally:
        if swapped:
            if backup is not None:
                servers.write_text(backup)
            else:
                servers.unlink(missing_ok=True)

    leaked = _leak_check(repo_root, overlay_only)
    ok = all(entry.get("ok") for entry in results) and not leaked
    step = {
        "step": "public",
        "ok": ok,
        "rendered_from": "servers.base.json" if swapped else "servers.json",
        "overlay_servers_excluded": overlay_only,
        "scripts": results,
    }
    if leaked:
        step["leak"] = leaked
        step["error"] = "overlay-only servers reached tracked files; inspect before committing"
    return step


def _render_local(repo_root: Path, home: Path) -> dict:
    """Patch ~/.claude.json with the effective server set, preserving secrets.

    Unlike the shell renderer this merges each server's `env` and `headers`
    rather than replacing them, so a value that only exists on this machine —
    a password kept out of every repo — survives the render.
    """
    target = home / ".claude.json"
    effective = _servers(repo_root / SERVERS_REL)
    if not effective:
        return {"step": "local", "ok": False, "error": f"no servers in {SERVERS_REL}"}
    if not target.is_file():
        return {"step": "local", "ok": False, "error": f"{target} not found"}

    try:
        live = json.loads(target.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return {"step": "local", "ok": False, "error": f"cannot read {target}: {exc}"}

    servers = dict(live.get("mcpServers") or {})
    changed: list[str] = []
    preserved: list[str] = []

    for name, cfg in effective.items():
        current = dict(servers.get(name) or {})
        merged = dict(current)
        for key, value in cfg.items():
            if key in ("env", "headers"):
                combined = dict(current.get(key) or {})
                combined.update(value or {})
                if combined != current.get(key):
                    merged[key] = combined
                elif current.get(key) is not None:
                    merged[key] = current[key]
                kept = sorted(set(current.get(key) or {}) - set(value or {}))
                if kept:
                    preserved.extend(f"{name}.{key}.{k}" for k in kept)
            elif key == "description":
                continue
            else:
                merged[key] = value
        if "url" in merged and "type" not in merged:
            merged["type"] = cfg.get("transport", "http")
        merged.pop("transport", None)
        if merged != current:
            servers[name] = merged
            changed.append(name)

    if changed:
        live["mcpServers"] = servers
        tmp = target.with_name(target.name + ".render-tmp")
        tmp.write_text(json.dumps(live, indent=2, ensure_ascii=False) + "\n")
        shutil.copymode(target, tmp)
        os.replace(tmp, target)

    return {
        "step": "local",
        "ok": True,
        "target": str(target),
        "updated_servers": changed,
        "preserved_local_values": sorted(set(preserved)),
    }


def _servers(path: Path) -> dict:
    return layout.read_json(path).get("servers") or {}


def _overlay_only_servers(repo_root: Path) -> list[str]:
    effective = _servers(repo_root / SERVERS_REL)
    base = _servers(repo_root / SERVERS_BASE_REL)
    return sorted(set(effective) - set(base))


def _leak_check(repo_root: Path, overlay_only: list[str]) -> list[dict]:
    """Report any tracked per-tool config that now names an overlay-only server."""
    if not overlay_only:
        return []
    found = []
    for rel in layout.PUBLIC_RENDERED:
        path = repo_root / rel
        candidates = [path] if path.is_file() else sorted(path.glob("*")) if path.is_dir() else []
        for candidate in candidates:
            try:
                text = candidate.read_text()
            except (OSError, UnicodeDecodeError):
                continue
            hits = [name for name in overlay_only if name in text]
            if hits:
                found.append({"path": str(candidate.relative_to(repo_root)), "servers": hits})
    return found
