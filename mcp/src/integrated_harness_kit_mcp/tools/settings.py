"""settings_get / settings_set — read and change Claude Code settings safely.

`claude/settings.json` is a render artifact now: a public base, plus each
enabled overlay's fragment, plus whatever Claude Code itself wrote at runtime.
Editing the artifact is therefore pointless — the next render discards it. These
tools write the source that owns the key and re-render, and `settings_get`
answers the question the merged file cannot: who set this.
"""

from __future__ import annotations

import json
from pathlib import Path

from .. import layout, repo_scripts
from ._common import need_repo

BASE_REL = "claude/settings.base.json"
LIVE_REL = "claude/settings.json"
OVERLAY_FRAGMENT = "settings/claude.json"


def settings_get(key: str | None = None, repo_path: str | None = None) -> dict:
    """Effective settings with per-key provenance.

    Args:
        key: a top-level key, or a dotted path like "permissions.defaultMode".
             Omit for everything.

    Provenance is one of: base, overlay:<alias>, overlay:<alias>:local (the
    overlay's machine-only settings/claude.local.json), runtime (written by
    Claude Code and preserved by the renderer), or missing.
    """
    repo_root, fail = need_repo(repo_path)
    if fail:
        return fail

    live = layout.read_json(repo_root / LIVE_REL)
    sources = _sources(repo_root)

    if key:
        value, found = _dig(live, key)
        if not found:
            return {"ok": False, "error": f"{key} is not set", "repo": str(repo_root)}
        return {
            "ok": True,
            "repo": str(repo_root),
            "key": key,
            "value": value,
            "from": _origin(key, sources),
        }

    return {
        "ok": True,
        "repo": str(repo_root),
        "keys": {
            name: {"value": value, "from": _origin(name, sources)}
            for name, value in sorted(live.items())
        },
    }


def settings_set(
    key: str,
    value=None,
    target: str = "base",
    remove: bool = False,
    repo_path: str | None = None,
) -> dict:
    """Set or remove a settings key in the base or in an overlay, then re-render.

    Args:
        key: top-level key or dotted path.
        value: JSON-able value. Ignored when remove=True.
        target: "base" (public, shared), "overlay:<alias>" (private,
                environment-specific — anything naming a host, account or path
                belongs here), or "overlay:<alias>:local" (this machine only,
                e.g. autoMode; the overlay's gitignored claude.local.json).
    """
    repo_root, fail = need_repo(repo_path)
    if fail:
        return fail
    if not key:
        return {"ok": False, "error": "key must not be empty"}

    shadow = None
    if target == "base":
        path = repo_root / BASE_REL
        local_only = _local_only_keys(repo_root)
        if key.split(".")[0] in local_only:
            return {
                "ok": False,
                "error": (
                    f"{key} is runtime state that must not be tracked "
                    f"(LOCAL_ONLY_KEYS={sorted(local_only)}); "
                    "use target 'overlay:<alias>:local' or leave it local"
                ),
            }
    elif target.startswith("overlay:"):
        alias, _, variant = target.split(":", 1)[1].partition(":")
        if variant not in ("", "local"):
            return {"ok": False, "error": f"unknown target {target!r}"}
        known = {entry.get("alias") for entry in layout.registered_overlays(repo_root)}
        if alias not in known:
            return {"ok": False, "error": f"no overlay registered as {alias!r}"}
        path = layout.overlay_root(repo_root, alias) / OVERLAY_FRAGMENT
        if variant:
            path = path.with_suffix(".local.json")
        else:
            shadow = path.with_suffix(".local.json")
    else:
        return {"ok": False, "error": f"unknown target {target!r}"}

    data = layout.read_json(path) if path.is_file() else {}
    if remove:
        if not _drop(data, key):
            return {"ok": False, "error": f"{key} is not set in {path.name}"}
    else:
        _place(data, key, value)

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    except OSError as exc:
        return {"ok": False, "error": f"cannot write {path}: {exc}"}

    rendered = _render(repo_root)
    result = {
        "ok": rendered.get("ok", False),
        "repo": str(repo_root),
        "key": key,
        "target": target,
        "wrote": str(path.relative_to(repo_root)),
        "render": rendered,
    }
    if shadow is not None and shadow.is_file() and _dig(layout.read_json(shadow), key)[1]:
        result["warning"] = f"{key} is also set in {shadow.name}, which wins on this machine"
    return result


def _render(repo_root: Path) -> dict:
    module = repo_scripts.load(repo_root, "render_settings")
    if module is None or not hasattr(module, "render_all"):
        return {"ok": False, "error": "repo has no render_settings.render_all()"}
    try:
        with repo_scripts.scripts_on_path(repo_root):
            module.render_all(repo_root)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return {"ok": True, "written": sorted(layout.ARTIFACTS)}


def _local_only_keys(repo_root: Path) -> set[str]:
    module = repo_scripts.load(repo_root, "render_settings")
    return set(getattr(module, "LOCAL_ONLY_KEYS", ()) or ())


def _sources(repo_root: Path) -> list[tuple[str, dict]]:
    """(label, mapping) from lowest to highest precedence."""
    out: list[tuple[str, dict]] = [("base", layout.read_json(repo_root / BASE_REL))]
    for entry in layout.registered_overlays(repo_root):
        alias = entry.get("alias", "")
        if not entry.get("enabled", True):
            continue
        fragment = layout.overlay_root(repo_root, alias) / OVERLAY_FRAGMENT
        if fragment.is_file():
            out.append((f"overlay:{alias}", layout.read_json(fragment)))
        # The renderer merges this machine's sibling right after the fragment.
        local = fragment.with_suffix(".local.json")
        if local.is_file():
            out.append((f"overlay:{alias}:local", layout.read_json(local)))
    return out


def _origin(key: str, sources: list[tuple[str, dict]]) -> str:
    winner = "runtime"
    for label, mapping in sources:
        _, found = _dig(mapping, key)
        if found:
            winner = label
    return winner


def _dig(data: dict, key: str):
    node = data
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None, False
        node = node[part]
    return node, True


def _place(data: dict, key: str, value) -> None:
    parts = key.split(".")
    node = data
    for part in parts[:-1]:
        nxt = node.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            node[part] = nxt
        node = nxt
    node[parts[-1]] = value


def _drop(data: dict, key: str) -> bool:
    parts = key.split(".")
    node = data
    for part in parts[:-1]:
        nxt = node.get(part)
        if not isinstance(nxt, dict):
            return False
        node = nxt
    return node.pop(parts[-1], _MISSING) is not _MISSING


_MISSING = object()
