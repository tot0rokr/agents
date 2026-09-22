#!/usr/bin/env python3
"""Render the tool-facing config artifacts from tracked bases plus overlay fragments.

Two artifacts today: claude/settings.json and shared/mcp/servers.json.

Design and rationale: docs/overlay.md
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

BASE_REL = "claude/settings.base.json"
LIVE_REL = "claude/settings.json"
STATE_REL = "overlays/rendered.local.json"
FRAGMENT_REL = "settings/claude.json"

MCP_BASE_REL = "shared/mcp/servers.base.json"
MCP_LIVE_REL = "shared/mcp/servers.json"
MCP_FRAGMENT_REL = "mcp/servers.json"

MEMORY_BASE_REL = "shared/memory/MEMORY.base.md"
MEMORY_LIVE_REL = "shared/memory/MEMORY.md"
MEMORY_FRAGMENT_REL = "memory/MEMORY.md"

# Written by Claude Code at runtime and environment-describing. Never tracked.
LOCAL_ONLY_KEYS = ("autoMode",)

_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

KeyPath = tuple[str, ...]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def dumps(obj: Any) -> str:
    """Single serializer for every file this harness writes, so renders don't churn."""
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


def deep_merge(base: dict, patch: dict) -> dict:
    out = dict(base)
    for key, val in patch.items():
        cur = out.get(key)
        out[key] = deep_merge(cur, val) if isinstance(cur, dict) and isinstance(val, dict) else val
    return out


def substitute(obj: Any, variables: dict[str, str]) -> Any:
    if isinstance(obj, str):
        return _VAR.sub(lambda m: str(variables.get(m.group(1), m.group(0))), obj)
    if isinstance(obj, dict):
        return {k: substitute(v, variables) for k, v in obj.items()}
    if isinstance(obj, list):
        return [substitute(v, variables) for v in obj]
    return obj


def key_paths(obj: dict, prefix: KeyPath = ()) -> set[KeyPath]:
    out: set[KeyPath] = set()
    for key, val in obj.items():
        path = prefix + (key,)
        out.add(path)
        if isinstance(val, dict):
            out |= key_paths(val, path)
    return out


def preserve_unmanaged(
    live: dict,
    managed: dict,
    dropped: frozenset[KeyPath] = frozenset(),
    prefix: KeyPath = (),
) -> dict:
    """Carry live-only keys into the render, minus ones a past render managed.

    Without the `dropped` set a key deleted from the base would live on in the
    artifact forever, since the previous render wrote it into the live file.
    """
    out = dict(managed)
    for key, val in live.items():
        path = prefix + (key,)
        if key in out:
            if isinstance(val, dict) and isinstance(out[key], dict):
                out[key] = preserve_unmanaged(val, out[key], dropped, path)
        elif path not in dropped:
            out[key] = val
    return out


def check_base(base: dict) -> list[str]:
    return [key for key in LOCAL_ONLY_KEYS if key in base]


def collect_fragments(repo_root: Path, rel: str = FRAGMENT_REL) -> list[dict]:
    from overlay import enabled_overlays  # local import: overlay imports this module

    fragments = []
    for entry in enabled_overlays(repo_root):
        fragment = entry.path / rel
        if fragment.is_file():
            fragments.append(substitute(load_json(fragment), entry.variables()))
    return fragments


def _load_state(repo_root: Path) -> set[KeyPath]:
    state = repo_root / STATE_REL
    if not state.is_file():
        return set()
    return {tuple(path) for path in json.loads(state.read_text()).get("managed", [])}


def _save_state(repo_root: Path, managed: set[KeyPath]) -> None:
    state = repo_root / STATE_REL
    state.parent.mkdir(parents=True, exist_ok=True)
    payload = json.loads(state.read_text()) if state.is_file() else {}
    payload["managed"] = sorted(list(path) for path in managed)
    state.write_text(dumps(payload))


def _write_atomic(target: Path, text: str) -> None:
    tmp = target.with_name(target.name + ".render-tmp")
    tmp.write_text(text)
    if target.exists():
        shutil.copymode(target, tmp)
    os.replace(tmp, target)


def render(
    repo_root: Path,
    fragments: list[dict] | None = None,
    write: bool = True,
) -> dict:
    base_path = repo_root / BASE_REL
    live_path = repo_root / LIVE_REL

    base = load_json(base_path)
    violations = check_base(base)
    if violations:
        raise ValueError(f"{BASE_REL} must not track local-only keys: {', '.join(violations)}")

    if fragments is None:
        fragments = collect_fragments(repo_root)

    merged = base
    for fragment in fragments:
        merged = deep_merge(merged, fragment)

    managed = key_paths(merged)
    if live_path.is_file():
        dropped = _load_state(repo_root) - managed
        merged = preserve_unmanaged(load_json(live_path), merged, frozenset(dropped))

    if write:
        _write_atomic(live_path, dumps(merged))
        _save_state(repo_root, managed)
    return merged


def render_mcp(repo_root: Path, fragments: list[dict] | None = None, write: bool = True) -> dict:
    """Merge overlay MCP servers onto the tracked base. Nothing writes this at
    runtime, so unlike settings it needs no live-state preservation."""
    base_path = repo_root / MCP_BASE_REL
    if not base_path.is_file():
        return {}

    merged = load_json(base_path)
    if fragments is None:
        fragments = collect_fragments(repo_root, MCP_FRAGMENT_REL)
    for fragment in fragments:
        merged = deep_merge(merged, fragment)

    if write:
        _write_atomic(repo_root / MCP_LIVE_REL, dumps(merged))
    return merged


def render_memory(repo_root: Path, write: bool = True) -> str:
    """Concatenate the memory index: base, then each overlay's fragment.

    The index is a flat list of pointer lines, and the agents append to it at
    runtime, so lines the live file has and no source claims are carried over —
    the line-level equivalent of what `preserve_unmanaged` does for settings.
    """
    base_path = repo_root / MEMORY_BASE_REL
    if not base_path.is_file():
        return ""

    sections = [base_path.read_text().rstrip("\n")]
    managed: set[str] = set()
    for line in sections[0].splitlines():
        managed.add(line.strip())

    for entry in _memory_fragments(repo_root):
        text = entry.rstrip("\n")
        if not text:
            continue
        sections.append(text)
        for line in text.splitlines():
            managed.add(line.strip())

    live_path = repo_root / MEMORY_LIVE_REL
    if live_path.is_file():
        previous = _load_memory_state(repo_root)
        carried = [
            line
            for line in live_path.read_text().splitlines()
            if line.strip() and line.strip() not in managed and line.strip() not in previous
        ]
        if carried:
            sections.append("\n".join(carried))

    rendered = "\n\n".join(sections) + "\n"
    if write:
        _write_atomic(live_path, rendered)
        _save_memory_state(repo_root, managed)
    return rendered


def _memory_fragments(repo_root: Path) -> list[str]:
    from overlay import enabled_overlays

    out = []
    for entry in enabled_overlays(repo_root):
        fragment = entry.path / MEMORY_FRAGMENT_REL
        if fragment.is_file():
            out.append(substitute(fragment.read_text(), entry.variables()))
    return out


def _load_memory_state(repo_root: Path) -> set[str]:
    state = repo_root / STATE_REL
    if not state.is_file():
        return set()
    return set(json.loads(state.read_text()).get("memoryLines", []))


def _save_memory_state(repo_root: Path, managed: set[str]) -> None:
    state = repo_root / STATE_REL
    state.parent.mkdir(parents=True, exist_ok=True)
    payload = json.loads(state.read_text()) if state.is_file() else {}
    payload["memoryLines"] = sorted(managed)
    state.write_text(dumps(payload))


def render_all(repo_root: Path, write: bool = True) -> dict[str, dict | str]:
    return {
        LIVE_REL: render(repo_root, write=write),
        MCP_LIVE_REL: render_mcp(repo_root, write=write),
        MEMORY_LIVE_REL: render_memory(repo_root, write=write),
    }


def init_base(repo_root: Path, write: bool = True) -> dict:
    """Seed the tracked bases from the live artifacts, minus local-only keys."""
    live = load_json(repo_root / LIVE_REL)
    base = {k: v for k, v in live.items() if k not in LOCAL_ONLY_KEYS}
    if write:
        _write_atomic(repo_root / BASE_REL, dumps(base))
        mcp_base = repo_root / MCP_BASE_REL
        mcp_live = repo_root / MCP_LIVE_REL
        if not mcp_base.is_file() and mcp_live.is_file():
            _write_atomic(mcp_base, dumps(load_json(mcp_live)))
    return base


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Render claude/settings.json.")
    p.add_argument("--repo", type=Path, default=None, help="override repo root")
    p.add_argument("--check", action="store_true", help="verify the base tracks no local-only keys")
    p.add_argument("--init-base", action="store_true", help="seed the base from the live file")
    p.add_argument("--dry-run", action="store_true", help="print the render instead of writing")
    args = p.parse_args(argv)

    repo_root = (args.repo or Path(__file__).resolve().parent.parent).resolve()

    if args.check:
        violations = check_base(load_json(repo_root / BASE_REL))
        if violations:
            print(f"FAIL  {BASE_REL} tracks local-only keys: {', '.join(violations)}", file=sys.stderr)
            return 1
        print(f"OK    {BASE_REL} has no local-only keys")
        return 0

    if args.init_base:
        base = init_base(repo_root, write=not args.dry_run)
        if args.dry_run:
            print(dumps(base), end="")
        else:
            print(f"wrote {BASE_REL} ({len(base)} top-level keys)")
        return 0

    try:
        rendered = render_all(repo_root, write=not args.dry_run)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"render failed: {exc}", file=sys.stderr)
        return 1

    for rel, merged in rendered.items():
        if not merged:
            continue
        if args.dry_run:
            print(f"--- {rel}")
            print(dumps(merged), end="")
        else:
            print(f"wrote {rel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
