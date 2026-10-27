#!/usr/bin/env python3
"""Render the tool-facing config artifacts from tracked bases plus overlay fragments.

Five artifacts today: claude/settings.json, shared/mcp/servers.json,
shared/memory/MEMORY.md, codex/config.toml and codex/AGENTS.override.md.

Design and rationale: docs/overlay.md
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
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

CODEX_BASE_REL = "codex/config.base.toml"
CODEX_LIVE_REL = "codex/config.toml"
CODEX_FRAGMENT_REL = "settings/codex.toml"
CODEX_STATE_KEY = "codexManaged"
# It carries overlay MCP servers, and with them their credentials.
CODEX_MODE = 0o600

AGENTS_SOURCE_REL = "shared/AGENTS.md"
CODEX_AGENTS_REL = "codex/AGENTS.override.md"

# Written by Claude Code at runtime and environment-describing. Never tracked.
LOCAL_ONLY_KEYS = ("autoMode",)

_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

KeyPath = tuple[str, ...]

# Never in codex/config.base.toml: trusted projects are machine paths (an
# overlay's settings/codex.toml holds them), MCP servers come from
# shared/mcp/, and the NUX counters are Codex's own UI state.
CODEX_LOCAL_ONLY: tuple[KeyPath, ...] = (
    ("projects",),
    ("mcp_servers",),
    ("tui", "model_availability_nux"),
)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def dumps(obj: Any) -> str:
    """Single serializer for every file this harness writes, so renders don't churn."""
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


def deep_merge(base: dict, patch: dict) -> dict:
    """Objects merge key by key; lists replace — unless the key asks to append.

    A source that wants to add to a list rather than own it writes the key with
    a trailing `+`:

        {"hooks": {"Stop+": [{...}]}}

    which appends to whatever `hooks.Stop` holds so far, in source order, and
    leaves the key itself named `Stop`. Without that, an overlay adding one
    hook would have to restate every hook the base defines.
    """
    out = dict(base)
    for key, val in patch.items():
        if key.endswith("+") and len(key) > 1:
            target = key[:-1]
            current = out.get(target)
            if isinstance(current, list) and isinstance(val, list):
                out[target] = current + val
            elif isinstance(current, dict) and isinstance(val, dict):
                out[target] = deep_merge(current, val)
            else:
                out[target] = _normalize(val)
            continue
        cur = out.get(key)
        if isinstance(cur, dict) and isinstance(val, dict):
            out[key] = deep_merge(cur, val)
        else:
            # Even when nothing is there to merge with, a nested `key+` has to
            # lose its marker — otherwise the next source appends to a key that
            # does not exist yet and the first source's list is dropped.
            out[key] = _normalize(val)
    return out


def _normalize(value):
    return deep_merge({}, value) if isinstance(value, dict) else value


def substitute(obj: Any, variables: dict[str, str], keys: bool = False) -> Any:
    """Expand ${VAR} in values, and in keys too when asked.

    TOML fragments need keys: a trusted project is `[projects."${CLAUDE_HOME}/x"]`.
    """
    if isinstance(obj, str):
        return _VAR.sub(lambda m: str(variables.get(m.group(1), m.group(0))), obj)
    if isinstance(obj, dict):
        return {
            (substitute(k, variables) if keys else k): substitute(v, variables, keys)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [substitute(v, variables, keys) for v in obj]
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

    # A sibling *.local.json (or *.local.toml) is this machine's override of the
    # overlay's own fragment (autoMode, for one, describes a single machine).
    # Overlays keep *.local.* out of git, so it never follows the overlay elsewhere.
    path = Path(rel)
    local_rel = str(path.with_suffix(".local" + path.suffix))
    fragments = []
    for entry in enabled_overlays(repo_root):
        for fragment in (entry.path / rel, entry.path / local_rel):
            if not fragment.is_file():
                continue
            if fragment.suffix == ".toml":
                data = tomllib.loads(fragment.read_text())
                fragments.append(substitute(data, entry.variables(), keys=True))
            else:
                fragments.append(substitute(load_json(fragment), entry.variables()))
    return fragments


def _load_state(repo_root: Path, key: str = "managed") -> set[KeyPath]:
    state = repo_root / STATE_REL
    if not state.is_file():
        return set()
    return {tuple(path) for path in json.loads(state.read_text()).get(key, [])}


def _save_state(repo_root: Path, managed: set[KeyPath], key: str = "managed") -> None:
    state = repo_root / STATE_REL
    state.parent.mkdir(parents=True, exist_ok=True)
    payload = json.loads(state.read_text()) if state.is_file() else {}
    payload[key] = sorted(list(path) for path in managed)
    state.write_text(dumps(payload))


def _write_atomic(target: Path, text: str, mode: int | None = None) -> None:
    tmp = target.with_name(target.name + ".render-tmp")
    if mode is None:
        tmp.write_text(text)
        if target.exists():
            shutil.copymode(target, tmp)
    else:
        # Created private rather than chmod-ed afterwards, so the content is
        # never readable by others, not even for a moment.
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
        os.chmod(tmp, mode)
    os.replace(tmp, target)


def artifact_current(repo_root: Path, rel: str, rendered: dict | str) -> bool:
    """Whether the file on disk already holds `rendered`.

    JSON and TOML compare as data. Claude Code and Codex rewrite their own files
    in their own key order and formatting, and that is not drift. Leaving a file
    that is already current untouched also keeps a running session's file
    watcher quiet.
    """
    path = repo_root / rel
    if not path.is_file():
        return False
    text = path.read_text()
    try:
        if rel.endswith(".json"):
            return json.loads(text) == rendered
        if rel.endswith(".toml"):
            return tomllib.loads(text) == rendered
    except ValueError:
        return False
    return text == rendered


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
        if not artifact_current(repo_root, LIVE_REL, merged):
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

    if write and not artifact_current(repo_root, MCP_LIVE_REL, merged):
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
        if not artifact_current(repo_root, MEMORY_LIVE_REL, rendered):
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


# The stdlib reads TOML but cannot write it, and the harness takes no
# dependencies, so this covers what tomllib can hand back.

_BARE_KEY = re.compile(r"[A-Za-z0-9_-]+")
_TOML_ESCAPES = {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\t": "\\t", "\n": "\\n", "\f": "\\f", "\r": "\\r"}


def _toml_str(text: str) -> str:
    # Not json.dumps: it writes characters outside the BMP as surrogate pairs,
    # which TOML rejects, and leaves DEL unescaped.
    out = []
    for ch in text:
        if ch in _TOML_ESCAPES:
            out.append(_TOML_ESCAPES[ch])
        elif ch < " " or ch == "\x7f":
            out.append(f"\\u{ord(ch):04X}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def _toml_key(key: str) -> str:
    return key if _BARE_KEY.fullmatch(key) else _toml_str(key)


def _toml_value(value: Any, path: KeyPath) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return _toml_str(value)
    if isinstance(value, (datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(v, path) for v in value) + "]"
    if isinstance(value, dict):
        if not value:
            return "{}"
        items = ", ".join(f"{_toml_key(k)} = {_toml_value(v, path + (k,))}" for k, v in value.items())
        return "{ " + items + " }"
    raise ValueError(f"{'.'.join(path)}: {type(value).__name__} has no TOML form")


def _is_table_array(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(v, dict) for v in value)


def _emit_table(table: dict, path: KeyPath, lines: list[str], header: str | None = None) -> None:
    scalars = [(k, v) for k, v in table.items() if not isinstance(v, dict) and not _is_table_array(v)]
    # A table that holds only sub-tables needs no header of its own. An empty
    # one does, or it would vanish.
    if header or (path and (scalars or not table)):
        lines += ["", header or "[" + ".".join(map(_toml_key, path)) + "]"]
    lines += [f"{_toml_key(k)} = {_toml_value(v, path + (k,))}" for k, v in scalars]
    for key, value in table.items():
        sub = path + (key,)
        if isinstance(value, dict):
            _emit_table(value, sub, lines)
        elif _is_table_array(value):
            for item in value:
                _emit_table(item, sub, lines, "[[" + ".".join(map(_toml_key, sub)) + "]]")


def dumps_toml(data: dict, comment: str = "") -> str:
    """Serialize, then read the text back: a file Codex would parse differently is never written."""
    body: list[str] = []
    _emit_table(data, (), body)
    while body and not body[0]:
        body.pop(0)
    head = [f"# {line}".rstrip() for line in comment.splitlines()]
    text = "\n".join(head + ([""] if head and body else []) + body) + "\n"
    if tomllib.loads(text) != data:
        raise ValueError("TOML serializer produced text that reads back differently")
    return text


CODEX_HEADER = (
    "Rendered by scripts/render_settings.py from codex/config.base.toml, the MCP\n"
    "servers in shared/mcp/ and each overlay's settings/codex.toml. Codex writes\n"
    "here too and the keys it adds are kept, but comments are not. Edit the sources."
)


def _warn(message: str) -> None:
    print(f"warning: {message}", file=sys.stderr)


def check_codex_base(base: dict) -> list[str]:
    found = []
    for path in CODEX_LOCAL_ONLY:
        node: Any = base
        for key in path:
            node = node.get(key) if isinstance(node, dict) else None
        if node is not None:
            found.append(".".join(path))
    return found


def codex_mcp_servers(servers_doc: dict) -> dict:
    """Map the canonical server list onto Codex's [mcp_servers.<name>] tables.

    Codex rejects its whole config over one malformed server table, so a server
    it cannot run is left out with a warning instead.
    """
    out = {}
    for name, cfg in (servers_doc.get("servers") or {}).items():
        if cfg.get("url"):
            transport = cfg.get("transport", "http")
            if transport != "http":
                _warn(f"codex: skipped MCP server {name!r}; Codex has no {transport} transport")
                continue
            entry: dict[str, Any] = {"url": str(cfg["url"])}
            if cfg.get("headers"):
                entry["http_headers"] = {str(k): str(v) for k, v in cfg["headers"].items()}
        elif cfg.get("command"):
            entry = {"command": str(cfg["command"])}
            if cfg.get("args"):
                entry["args"] = [str(a) for a in cfg["args"]]
            if cfg.get("env"):
                entry["env"] = {str(k): str(v) for k, v in cfg["env"].items()}
        else:
            _warn(f"codex: skipped MCP server {name!r}; it has neither url nor command")
            continue
        if cfg.get("enabled") is False:
            entry["enabled"] = False
        out[name] = entry
    return out


def _tracked(repo_root: Path, rel: str) -> bool:
    try:
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", rel], cwd=repo_root, capture_output=True
        )
    except OSError:
        return False
    return result.returncode == 0


def render_codex(
    repo_root: Path,
    servers: dict | None = None,
    fragments: list[dict] | None = None,
    write: bool = True,
) -> dict:
    """Render codex/config.toml the way `render` does Claude's settings.

    Base, then the MCP servers, then overlay fragments, and over that every key
    the live file has that no source claims. Those are what Codex writes for
    itself: trusted projects, UI state, whatever a newer version adds.
    """
    base_path = repo_root / CODEX_BASE_REL
    if not base_path.is_file():
        return {}

    base = tomllib.loads(base_path.read_text())
    violations = check_codex_base(base)
    if violations:
        raise ValueError(f"{CODEX_BASE_REL} must not hold: {', '.join(violations)}")

    if servers is None:
        servers = render_mcp(repo_root, write=False)
    merged = base
    mcp = codex_mcp_servers(servers)
    if mcp:
        merged = deep_merge(merged, {"mcp_servers": mcp})
    if fragments is None:
        fragments = collect_fragments(repo_root, CODEX_FRAGMENT_REL)
    for fragment in fragments:
        merged = deep_merge(merged, fragment)

    managed = key_paths(merged)
    live_path = repo_root / CODEX_LIVE_REL
    if live_path.is_file():
        # A live file that does not parse is stopped on, not rendered over:
        # that would throw away whatever Codex had written there.
        live = tomllib.loads(live_path.read_text())
        dropped = _load_state(repo_root, CODEX_STATE_KEY) - managed
        merged = preserve_unmanaged(live, merged, frozenset(dropped))

    if write:
        if _tracked(repo_root, CODEX_LIVE_REL):
            raise ValueError(
                f"{CODEX_LIVE_REL} is tracked by git, so overlay content would land in a "
                f"tracked file; run 'git rm --cached {CODEX_LIVE_REL}' first"
            )
        if not artifact_current(repo_root, CODEX_LIVE_REL, merged):
            _write_atomic(live_path, dumps_toml(merged, CODEX_HEADER), CODEX_MODE)
        elif live_path.stat().st_mode & 0o777 != CODEX_MODE:
            os.chmod(live_path, CODEX_MODE)
        _save_state(repo_root, managed, CODEX_STATE_KEY)
    return merged


_INSTRUCTION_LINE = re.compile(r"^See \[[^\]]*\]\(\./(instructions/[^)]+\.md)\)")
_RELATIVE_LINK = re.compile(r"\]\((\.\.?/[^)\s]+)\)")
_FENCE = re.compile(r"^\s*(```|~~~)")

CODEX_AGENTS_HEADER = (
    "<!-- Rendered by scripts/render_settings.py from shared/AGENTS.md with every\n"
    "linked instructions/*.md inlined, because Codex does not follow links. Codex\n"
    "reads this in place of AGENTS.md. Edit the sources, then re-render. -->"
)


def _absolute_links(line: str, base_dir: Path) -> str:
    return _RELATIVE_LINK.sub(lambda m: f"]({os.path.normpath(base_dir / m.group(1))})", line)


def _inline_instruction(path: Path) -> list[str]:
    """The file's body without its title, one heading level down, links made absolute."""
    lines = path.read_text().splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    while lines and not lines[0].strip():
        lines = lines[1:]
    out, fenced = [], False
    for line in lines:
        if _FENCE.match(line):
            fenced = not fenced
        elif not fenced:
            if line.startswith("#"):
                line = "#" + line
            line = _absolute_links(line, path.parent)
        out.append(line)
    return out


def render_codex_agents(repo_root: Path, write: bool = True) -> str:
    """Write Codex's global instructions with the linked instruction files inlined.

    Codex reads AGENTS.override.md in place of AGENTS.md, so the tracked
    symlink stays as it is, and a checkout that has not rendered yet still
    gets instructions, only the thin ones.
    """
    source = repo_root / AGENTS_SOURCE_REL
    if not source.is_file():
        return ""

    base_dir = Path(os.path.abspath(source.parent))
    out = [CODEX_AGENTS_HEADER, ""]
    for line in source.read_text().splitlines():
        match = _INSTRUCTION_LINE.match(line)
        if match:
            target = base_dir / match.group(1)
            # personal.md and the like exist only where an overlay supplies them.
            if target.is_file():
                out += _inline_instruction(target)
            continue
        out.append(_absolute_links(line, base_dir))

    rendered = "\n".join(out).rstrip("\n") + "\n"
    if write and not artifact_current(repo_root, CODEX_AGENTS_REL, rendered):
        _write_atomic(repo_root / CODEX_AGENTS_REL, rendered)
    return rendered


def serialize(rel: str, value: dict | str) -> str:
    if isinstance(value, str):
        return value
    if rel.endswith(".toml"):
        return dumps_toml(value, CODEX_HEADER)
    return dumps(value)


def render_all(repo_root: Path, write: bool = True) -> dict[str, dict | str]:
    servers = render_mcp(repo_root, write=write)
    return {
        LIVE_REL: render(repo_root, write=write),
        MCP_LIVE_REL: servers,
        MEMORY_LIVE_REL: render_memory(repo_root, write=write),
        CODEX_LIVE_REL: render_codex(repo_root, servers=servers, write=write),
        CODEX_AGENTS_REL: render_codex_agents(repo_root, write=write),
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
    p = argparse.ArgumentParser(
        description="Render claude/settings.json, shared/mcp/servers.json, shared/memory/MEMORY.md, "
        "codex/config.toml and codex/AGENTS.override.md."
    )
    p.add_argument("--repo", type=Path, default=None, help="override repo root")
    p.add_argument("--check", action="store_true", help="verify the bases track no local-only keys")
    p.add_argument("--init-base", action="store_true", help="seed the base from the live file")
    p.add_argument("--dry-run", action="store_true", help="print the render instead of writing")
    args = p.parse_args(argv)

    repo_root = (args.repo or Path(__file__).resolve().parent.parent).resolve()

    if args.check:
        failed = False
        violations = check_base(load_json(repo_root / BASE_REL))
        if violations:
            print(f"FAIL  {BASE_REL} tracks local-only keys: {', '.join(violations)}", file=sys.stderr)
            failed = True
        else:
            print(f"OK    {BASE_REL} has no local-only keys")
        codex_base = repo_root / CODEX_BASE_REL
        if codex_base.is_file():
            violations = check_codex_base(tomllib.loads(codex_base.read_text()))
            if violations:
                print(f"FAIL  {CODEX_BASE_REL} tracks local-only keys: {', '.join(violations)}", file=sys.stderr)
                failed = True
            else:
                print(f"OK    {CODEX_BASE_REL} has no local-only keys")
        return 1 if failed else 0

    if args.init_base:
        base = init_base(repo_root, write=not args.dry_run)
        if args.dry_run:
            print(dumps(base), end="")
        else:
            print(f"wrote {BASE_REL} ({len(base)} top-level keys)")
        return 0

    try:
        rendered = render_all(repo_root, write=not args.dry_run)
        for rel, merged in rendered.items():
            if not merged:
                continue
            if args.dry_run:
                print(f"--- {rel}")
                print(serialize(rel, merged), end="")
            else:
                print(f"rendered {rel}")
    except (OSError, ValueError) as exc:
        print(f"render failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
