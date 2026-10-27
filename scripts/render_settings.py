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
from pathlib import Path
from typing import Any

# tomllib is stdlib only from 3.11, and tomli is the package it was taken
# from. With neither, only the Codex render is skipped: every other artifact is
# JSON or Markdown, and failing here at import would leave a fresh install on
# 3.9 or 3.10 without claude/settings.json and stop overlay.py altogether.
try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None
NO_TOML_READER = "no TOML reader: needs Python 3.11+ or the tomli package"

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
# servers.json and codex/config.toml carry overlay MCP servers, and with them
# their credentials. Either one left readable exposes them, so both are private.
PRIVATE_MODE = 0o600
# overlays/ holds the overlay clones and their credentials; owner only.
OVERLAYS_MODE = 0o700
# How often a render merges again because Codex wrote the file meanwhile.
CODEX_RENDER_ATTEMPTS = 5

AGENTS_SOURCE_REL = "shared/AGENTS.md"
CODEX_AGENTS_REL = "codex/AGENTS.override.md"

# Written by Claude Code at runtime and environment-describing. Never tracked.
LOCAL_ONLY_KEYS = ("autoMode",)

_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
# An Authorization header Codex can build from the environment by itself.
_BEARER_VAR = re.compile(r"Bearer \$\{([A-Za-z_][A-Za-z0-9_]*)\}", re.IGNORECASE)

KeyPath = tuple[str, ...]

# Never in codex/config.base.toml: trusted projects are machine paths (an
# overlay's settings/codex.toml holds them), MCP servers come from
# shared/mcp/, and the NUX counters are Codex's own UI state.
CODEX_LOCAL_ONLY: tuple[KeyPath, ...] = (
    ("projects",),
    ("mcp_servers",),
    ("tui", "model_availability_nux"),
)

# Tables a tool reads as one unit: a render that drops one drops all of it,
# whatever the tool added inside (`*` matches any one key). What Codex writes
# into a server table (`enabled`, tool approvals) is no server without the
# `command` or `url` a source gave it, and Codex refuses the whole file over
# it ("invalid transport"); a model provider without its `name`, or an otel
# exporter without its `endpoint`, is refused the same way. Claude Code's
# status line and file suggestion objects need their `type` and `command`,
# and Claude Code skips a settings file that fails validation, not just the
# bad key.
CODEX_ATOMIC: tuple[KeyPath, ...] = (
    ("mcp_servers", "*"),
    ("model_providers", "*"),
    ("otel",),
)
CLAUDE_ATOMIC: tuple[KeyPath, ...] = (
    ("statusLine",),
    ("subagentStatusLine",),
    ("fileSuggestion",),
)

# The [mcp_servers.<name>] keys Codex 0.163 accepts on one transport only. One
# key of each in the same table and Codex rejects the whole config ("url is not
# supported for stdio"). The rest (enabled, required, the timeouts,
# enabled_tools, disabled_tools, scopes, tools) work on either.
CODEX_MCP_TRANSPORT_KEYS = {
    "url": (
        "url", "bearer_token_env_var", "http_headers", "env_http_headers",
        "http_headers_helper", "oauth", "oauth_resource", "auth",
    ),
    "command": ("command", "args", "env", "env_vars", "cwd"),
}


def load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} does not parse: {exc}") from exc


def parse_toml(text: str, path: Path, hint: str = "") -> dict[str, Any]:
    """Parse TOML read from `path`, naming that file when it does not parse.

    tomllib reports a line and a column but no file, and one render reads the
    base, every overlay's fragment and the live file.
    """
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"{path} does not parse: {exc}{hint}") from exc


def load_toml(path: Path, hint: str = "") -> dict[str, Any]:
    return parse_toml(path.read_text(), path, hint)


def dumps(obj: Any) -> str:
    """Single serializer for every file this harness writes, so renders don't churn."""
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


def deep_merge(base: dict, patch: dict, markers: bool = True) -> dict:
    """Objects merge key by key; lists replace — unless the key asks to append.

    A source that wants to add to a list rather than own it writes the key with
    a trailing `+`:

        {"hooks": {"Stop+": [{...}]}}

    which appends to whatever `hooks.Stop` holds so far, in source order, and
    leaves the key itself named `Stop`. Without that, an overlay adding one
    hook would have to restate every hook the base defines.

    `markers=False` takes every key literally. Codex's config keys trusted
    projects by path, and `[projects."/src/c++"]` is a project, not an append
    to `/src/c+`.
    """
    out = dict(base)
    for key, val in patch.items():
        if markers and key.endswith("+") and len(key) > 1:
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
            out[key] = deep_merge(cur, val, markers)
        else:
            # Even when nothing is there to merge with, a nested `key+` has to
            # lose its marker — otherwise the next source appends to a key that
            # does not exist yet and the first source's list is dropped.
            out[key] = _normalize(val, markers)
    return out


def _normalize(value, markers: bool = True):
    return deep_merge({}, value, markers) if isinstance(value, dict) else value


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


def _within(path: KeyPath, patterns: tuple[KeyPath, ...]) -> bool:
    """Whether `path` is one of `patterns` or lies inside one."""
    return any(
        len(pattern) <= len(path) and all(want in ("*", got) for want, got in zip(pattern, path))
        for pattern in patterns
    )


def preserve_unmanaged(
    live: dict,
    managed: dict,
    dropped: frozenset[KeyPath] = frozenset(),
    prefix: KeyPath = (),
    atomic: tuple[KeyPath, ...] = (),
) -> dict:
    """Carry live-only keys into the render, minus ones a past render managed.

    Without the `dropped` set a key deleted from the base would live on in the
    artifact forever, since the previous render wrote it into the live file.

    A dropped table loses only what a past render put in it. The tool may have
    added entries of its own since — Codex a project it was told to trust,
    Claude Code a plugin it installed — and those are no source's to take
    away; the table goes only once nothing else is left in it. A table in
    `atomic`, or inside one, is the exception and goes whole.
    """
    out = dict(managed)
    for key, val in live.items():
        path = prefix + (key,)
        if key in out:
            if isinstance(val, dict) and isinstance(out[key], dict):
                out[key] = preserve_unmanaged(val, out[key], dropped, path, atomic)
        elif path not in dropped:
            out[key] = val
        elif isinstance(val, dict) and not _within(path, atomic):
            kept = preserve_unmanaged(val, {}, dropped, path, atomic)
            if kept:
                out[key] = kept
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
                data = load_toml(fragment)
                fragments.append(substitute(data, entry.variables(), keys=True))
            else:
                fragments.append(substitute(load_json(fragment), entry.variables()))
    return fragments


def _load_state(repo_root: Path, key: str = "managed") -> set[KeyPath]:
    state = repo_root / STATE_REL
    if not state.is_file():
        return set()
    return {tuple(path) for path in load_json(state).get(key, [])}


def _state_path(repo_root: Path) -> Path:
    """overlays/rendered.local.json, creating overlays/ for its owner only.

    On a machine with no overlays yet the render is what creates the
    directory, and the clones that later land in it hold credentials, so it
    starts the way overlay.py keeps it.
    """
    state = repo_root / STATE_REL
    if not state.parent.is_dir():
        state.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(state.parent, OVERLAYS_MODE)
    return state


def _save_state(repo_root: Path, managed: set[KeyPath], key: str = "managed") -> None:
    state = _state_path(repo_root)
    payload = load_json(state) if state.is_file() else {}
    payload[key] = sorted(list(path) for path in managed)
    state.write_text(dumps(payload))


def _stage(target: Path, text: str, mode: int | None = None) -> Path:
    """Write `text` next to `target`, ready to be renamed over it."""
    tmp = target.with_name(target.name + ".render-tmp")
    if mode is None:
        tmp.write_text(text)
        if target.exists():
            shutil.copymode(target, tmp)
    else:
        # Private before the first byte is written, so the content is never
        # readable by others, not even for a moment. O_CREAT's mode does not
        # apply to a temp file an interrupted render left behind, hence fchmod.
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
        with os.fdopen(fd, "w") as fh:
            os.fchmod(fh.fileno(), mode)
            fh.write(text)
    return tmp


def _write_atomic(target: Path, text: str, mode: int | None = None) -> None:
    os.replace(_stage(target, text, mode), target)


Signature = tuple[int, int, int]


def _signature(st: os.stat_result) -> Signature:
    # Codex writes its config by renaming a new file over it, so each of its
    # writes changes the inode; size and mtime catch a writer that edits in place.
    return (st.st_ino, st.st_size, st.st_mtime_ns)


def _read_live(path: Path) -> tuple[str | None, Signature | None]:
    """The file's text, and the signature of the very file that text came from."""
    try:
        with open(path) as fh:
            return fh.read(), _signature(os.fstat(fh.fileno()))
    except FileNotFoundError:
        return None, None
    except IsADirectoryError:
        # Nothing to merge; a write then fails on it, as it always has.
        return None, _signature(path.stat())


def _replace_unless_changed(target: Path, text: str, mode: int, seen: Signature | None) -> bool:
    """Write like `_write_atomic`, unless `target` is no longer the file read as `seen`.

    A tool that writes the file while a render merges would otherwise lose that
    write to the rename. The check comes after the new content is staged, so
    only a stat separates it from the rename. Codex takes no lock on its config,
    so that last gap of microseconds cannot be closed from this side.
    """
    tmp = _stage(target, text, mode)
    # Renaming a file onto itself changes nothing, but it waits for the
    # directory lock, which a rename Codex has in flight holds until its file
    # is in place. Without this wait the stat below can still see the file
    # Codex is replacing, and the rename then lands right after Codex's.
    os.rename(tmp, tmp)
    try:
        current = _signature(target.stat())
    except FileNotFoundError:
        current = None
    if current != seen:
        tmp.unlink()
        return False
    try:
        os.replace(tmp, target)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise
    return True


def same_data(a: Any, b: Any, numbers_by_value: bool = False) -> bool:
    """`==` for parsed config, without Python's coercions between types.

    Python counts True == 1, False == 0 and 1 == 1.0 as equal; the tools that
    read these files do not. Codex refuses its whole config over an integer
    where it wants a boolean or a float where it wants an integer, and Claude
    Code drops a settings file that has a number where it wants a boolean. A
    live file holding one of those must not pass for current, or the render
    that would repair it is skipped. JSON is read by JavaScript, where 1 and
    1.0 are the same number, so `numbers_by_value` lets those two match.

    NaN equals itself here. Under == it never does, so a file holding one would
    never be current and could never get past dumps_toml's read-back check.
    """
    if numbers_by_value and type(a) in (int, float) and type(b) in (int, float):
        return a == b or (a != a and b != b)
    # Exact type, not isinstance: bool is a subclass of int.
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(same_data(v, b[k], numbers_by_value) for k, v in a.items())
    if isinstance(a, list):
        return len(a) == len(b) and all(same_data(x, y, numbers_by_value) for x, y in zip(a, b))
    return a == b or (a != a and b != b)


def artifact_current(repo_root: Path, rel: str, rendered: dict | str) -> bool:
    """Whether the file on disk already holds `rendered`.

    JSON and TOML compare as data. Claude Code and Codex rewrite their own files
    in their own key order and formatting, and that is not drift. Leaving a file
    that is already current untouched also keeps a running session's file
    watcher quiet. A value of another type is drift, though: see `same_data`.
    """
    path = repo_root / rel
    if not path.is_file():
        return False
    text = path.read_text()
    try:
        if rel.endswith(".json"):
            return same_data(json.loads(text), rendered, numbers_by_value=True)
        if rel.endswith(".toml"):
            return same_data(tomllib.loads(text), rendered)
    except ValueError:
        return False
    return text == rendered


def _tighten(path: Path) -> bool:
    """Make an existing file private in place; False when it is not ours to chmod.

    A file whose data is already current is not rewritten, so a running
    session's file watcher stays quiet, but one an older render or a hand copy
    left readable to others still has to be narrowed.
    """
    try:
        if path.stat().st_mode & 0o777 != PRIVATE_MODE:
            os.chmod(path, PRIVATE_MODE)
    except PermissionError:
        # Another user's file, left by a render run under sudo, say. Replacing
        # it needs only the directory, which is ours.
        return False
    except FileNotFoundError:
        # Gone since it was read; the caller writes it anew.
        return False
    return True


def _write_private(repo_root: Path, rel: str, rendered: dict, text: str) -> None:
    """Write a credential-bearing artifact readable by its owner only."""
    path = repo_root / rel
    if not artifact_current(repo_root, rel, rendered) or not _tighten(path):
        _write_atomic(path, text, PRIVATE_MODE)


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
        merged = preserve_unmanaged(load_json(live_path), merged, frozenset(dropped), atomic=CLAUDE_ATOMIC)

    if write:
        if not artifact_current(repo_root, LIVE_REL, merged):
            _write_atomic(live_path, dumps(merged))
        _save_state(repo_root, managed)
    return merged


def render_mcp(repo_root: Path, fragments: list[dict] | None = None, write: bool = True) -> dict:
    """Merge overlay MCP servers onto the tracked base. Nothing writes this at
    runtime, so unlike settings it needs no live-state preservation.

    It holds the same servers as codex/config.toml, with their headers and env,
    and a value an overlay takes from vars.local.json or servers.local.json
    lands here verbatim, so it is written private like that file.
    """
    base_path = repo_root / MCP_BASE_REL
    if not base_path.is_file():
        return {}

    merged = load_json(base_path)
    if fragments is None:
        fragments = collect_fragments(repo_root, MCP_FRAGMENT_REL)
    for fragment in fragments:
        merged = deep_merge(merged, fragment)

    if write:
        _write_private(repo_root, MCP_LIVE_REL, merged, dumps(merged))
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
    return set(load_json(state).get("memoryLines", []))


def _save_memory_state(repo_root: Path, managed: set[str]) -> None:
    state = _state_path(repo_root)
    payload = load_json(state) if state.is_file() else {}
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
    if not same_data(tomllib.loads(text), data):
        raise ValueError("TOML serializer produced text that reads back differently")
    return text


CODEX_HEADER = (
    "Rendered by scripts/render_settings.py from codex/config.base.toml, the MCP\n"
    "servers in shared/mcp/ and each overlay's settings/codex.toml. Codex writes\n"
    "here too and the keys it adds are kept, but comments are not. Edit the sources."
)

# Codex reads TOML 1.1 and tomllib only 1.0, so a live file Codex runs on can
# still fail here; the usual cause is something typed in by hand.
CODEX_LIVE_HINT = (
    " (Codex also accepts TOML 1.1, which Python's tomllib does not: rewrite an inline"
    " table that spans lines or ends in a comma as a [table], then render again)"
)


def _warn(message: str) -> None:
    print(f"warning: {message}", file=sys.stderr)


def _silent(message: str) -> None:
    """A warning a previous pass of the same render has already printed."""


def check_codex_base(base: dict) -> list[str]:
    found = []
    for path in CODEX_LOCAL_ONLY:
        node: Any = base
        for key in path:
            node = node.get(key) if isinstance(node, dict) else None
        if node is not None:
            found.append(".".join(path))
    return found


def _warn_unexpanded(warn, server: str, where: str, text: str) -> None:
    # The text itself is not printed: around the reference it may hold a value
    # substituted from vars.json.
    if "${" in text:
        warn(f"codex: MCP server {server!r} {where} has a ${{...}} that Codex does not expand; "
             "the server gets it as written")


def _codex_env(server: str, env: dict, warn=_warn) -> dict:
    """Map a stdio server's env onto Codex's `env` and `env_vars`.

    Claude Code expands ${VAR} in env when it starts a server; Codex passes the
    text through as is, and does not hand its own environment to the server
    either. So the way a token stays out of every repo, `"API_TOKEN":
    "${API_TOKEN}"`, becomes `env_vars = ["API_TOKEN"]`, which makes Codex copy
    that variable from its environment. env_vars cannot rename, so `"A": "${B}"`
    and a reference inside a longer value stay literal, with a warning.
    """
    out: dict[str, Any] = {}
    for key, value in env.items():
        key, value = str(key), str(value)
        ref = _VAR.fullmatch(value)
        if ref and ref.group(1) == key:
            out.setdefault("env_vars", []).append(key)
        else:
            _warn_unexpanded(warn, server, f"env {key}", value)
            out.setdefault("env", {})[key] = value
    return out


def _codex_headers(server: str, headers: dict, warn=_warn) -> dict:
    """Map an HTTP server's headers onto Codex's header fields.

    The same gap as env: Codex sends `Bearer ${TOKEN}` as written. It reads a
    header from the environment only through its own fields, `env_http_headers`
    for a whole value and `bearer_token_env_var` for `Authorization: Bearer`.
    """
    out: dict[str, Any] = {}
    for key, value in headers.items():
        key, value = str(key), str(value)
        bearer = _BEARER_VAR.fullmatch(value) if key.lower() == "authorization" else None
        ref = _VAR.fullmatch(value)
        if bearer:
            out["bearer_token_env_var"] = bearer.group(1)
        elif ref:
            out.setdefault("env_http_headers", {})[key] = ref.group(1)
        else:
            _warn_unexpanded(warn, server, f"header {key}", value)
            out.setdefault("http_headers", {})[key] = value
    return out


def codex_mcp_servers(servers_doc: dict, quiet: bool = False) -> dict:
    """Map the canonical server list onto Codex's [mcp_servers.<name>] tables.

    Codex rejects its whole config over one malformed server table, so a server
    it cannot run is left out with a warning instead.
    """
    warn = _silent if quiet else _warn
    out = {}
    for name, cfg in (servers_doc.get("servers") or {}).items():
        if cfg.get("url"):
            transport = cfg.get("transport", "http")
            if transport != "http":
                warn(f"codex: skipped MCP server {name!r}; Codex has no {transport} transport")
                continue
            entry: dict[str, Any] = {"url": str(cfg["url"])}
            _warn_unexpanded(warn, name, "url", entry["url"])
            entry.update(_codex_headers(name, cfg.get("headers") or {}, warn))
        elif cfg.get("command"):
            entry = {"command": str(cfg["command"])}
            if cfg.get("args"):
                entry["args"] = [str(a) for a in cfg["args"]]
            _warn_unexpanded(warn, name, "command line", " ".join([entry["command"], *entry.get("args", [])]))
            entry.update(_codex_env(name, cfg.get("env") or {}, warn))
        else:
            warn(f"codex: skipped MCP server {name!r}; it has neither url nor command")
            continue
        if cfg.get("enabled") is False:
            entry["enabled"] = False
        out[name] = entry
    return out


def drop_other_transport(live: dict, managed: dict, warn=_warn) -> dict:
    """Strip from each MCP server a source defines the live keys of the other transport.

    `preserve_unmanaged` carries every live-only key into the render, which is
    right for a timeout or a tool filter added in Codex, but not for transport
    keys: `codex mcp add linear -- npx ...` over a server the sources define by
    url leaves command and args in the live table, and so does a pre-harness
    config that install.py seeds. Next to the source's url they make a table
    Codex rejects, and the whole config with it. The source's transport wins,
    as every key a source claims does.
    """
    live_servers = live.get("mcp_servers")
    managed_servers = managed.get("mcp_servers")
    if not isinstance(live_servers, dict) or not isinstance(managed_servers, dict):
        return live
    servers = dict(live_servers)
    for name, table in managed_servers.items():
        current = servers.get(name)
        if not isinstance(table, dict) or not isinstance(current, dict):
            continue
        picked = [transport for transport in CODEX_MCP_TRANSPORT_KEYS if transport in table]
        # A fragment that only tunes a server (enabled = false) picks no transport.
        if len(picked) != 1:
            continue
        other = [
            key
            for transport, keys in CODEX_MCP_TRANSPORT_KEYS.items()
            if transport != picked[0]
            for key in keys
            if key in current
        ]
        if other:
            warn(f"codex: dropped {', '.join(other)} from MCP server {name!r}; the sources define it by {picked[0]}")
            servers[name] = {key: val for key, val in current.items() if key not in other}
    return {**live, "mcp_servers": servers}


def _drop_forwarded_literals(config: dict) -> dict:
    """Drop an env value that only restates a variable the server forwards.

    Codex takes `env` over `env_vars` for the same name, so a `"${NAME}"` an
    older render copied into the live file, and a lost render state then kept
    there, would beat the forwarding. A value typed by hand is kept.
    """
    servers = config.get("mcp_servers")
    if not isinstance(servers, dict):
        return config
    out = dict(servers)
    for name, server in servers.items():
        if not isinstance(server, dict) or not isinstance(server.get("env"), dict):
            continue
        forwarded = {var for var in server.get("env_vars") or [] if isinstance(var, str)}
        env = {k: v for k, v in server["env"].items() if not (k in forwarded and v == "${" + k + "}")}
        if len(env) == len(server["env"]):
            continue
        out[name] = {k: (env if k == "env" else v) for k, v in server.items() if k != "env" or env}
    return {**config, "mcp_servers": out}


def _merge_live(live: dict, managed: dict, dropped: frozenset[KeyPath], warn=_warn) -> dict:
    """The render: `managed`, plus what the live file holds that no source claims."""
    live = drop_other_transport(live, managed, warn)
    return _drop_forwarded_literals(preserve_unmanaged(live, managed, dropped, atomic=CODEX_ATOMIC))


def _tracked(repo_root: Path, rel: str) -> bool:
    try:
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", rel], cwd=repo_root, capture_output=True
        )
    except OSError:
        return False
    return result.returncode == 0


def _refuse_tracked_codex(repo_root: Path) -> None:
    if _tracked(repo_root, CODEX_LIVE_REL):
        raise ValueError(
            f"{CODEX_LIVE_REL} is tracked by git, so overlay content would land in a "
            f"tracked file; run 'git rm --cached {CODEX_LIVE_REL}' first"
        )


def _git_out(repo_root: Path, args: list[str], stdin: str | None = None) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args], cwd=repo_root, input=stdin, capture_output=True, text=True
        )
    except OSError:
        return None
    return result.stdout if result.returncode == 0 else None


def _has_state(repo_root: Path, key: str) -> bool:
    state = repo_root / STATE_REL
    return state.is_file() and key in load_json(state)


def last_checked_out_copy(repo_root: Path, rel: str) -> tuple[str, str] | None:
    """The newest copy of `rel` in a commit HEAD has pointed at, as (commit, text).

    Until 2026-10 codex/config.toml was tracked. Where Codex had not modified
    it, the pull that stopped tracking it deleted it, and the trusted projects
    and settings in it went too; that pull's previous HEAD still holds them.
    HEAD's reflog lists it, and ORIG_HEAD, which the pull set, still names it
    once the reflog has expired. A clone made after that commit never had the
    file checked out, so neither leads to a copy.
    """
    log = _git_out(repo_root, ["log", "--walk-reflogs", "--format=%H", "HEAD"])
    commits = log.split() if log else []
    orig = _git_out(repo_root, ["rev-parse", "-q", "--verify", "ORIG_HEAD^{commit}"])
    if orig:
        commits.append(orig.strip())
    commits = list(dict.fromkeys(commits))
    if not commits:
        return None
    found = _git_out(repo_root, ["cat-file", "--batch-check"], "".join(f"{c}:{rel}\n" for c in commits))
    for commit, line in zip(commits, (found or "").splitlines()):
        if line.split()[1:2] == ["blob"]:
            text = _git_out(repo_root, ["show", f"{commit}:{rel}"])
            return (commit, text) if text is not None else None
    return None


def _deleted_codex_copy(repo_root: Path) -> tuple[str, dict] | None:
    """What Codex held in codex/config.toml before a pull deleted it, as (commit, data).

    Only before the first Codex render on this checkout: once `codexManaged`
    is recorded, a missing file was removed on purpose and stays removed.
    """
    if _has_state(repo_root, CODEX_STATE_KEY):
        return None
    copy = last_checked_out_copy(repo_root, CODEX_LIVE_REL)
    if copy is None:
        return None
    commit, text = copy
    try:
        return commit, tomllib.loads(text)
    except ValueError:
        return None


def render_codex(
    repo_root: Path,
    servers: dict | None = None,
    fragments: list[dict] | None = None,
    write: bool = True,
    quiet: bool = False,
) -> dict:
    """Render codex/config.toml the way `render` does Claude's settings.

    Base, then the MCP servers, then overlay fragments, and over that every key
    the live file has that no source claims. Those are what Codex writes for
    itself: trusted projects, UI state, whatever a newer version adds. The one
    exception is an MCP server's keys of the other transport; see
    `drop_other_transport`. A live file the untracking pull deleted is read
    back from git (`_deleted_codex_copy`).

    Nothing here reads the `key+` append marker. Codex keys are data — project
    paths, server names — so a trailing `+` is part of the name, and the
    servers had their markers resolved when servers.json was rendered.

    A running Codex can write the file while this merges, when a directory is
    trusted or a model picked. Such a write is merged in again, not renamed
    over: the file is replaced only if it is still the one that was read.
    """
    base_path = repo_root / CODEX_BASE_REL
    if not base_path.is_file():
        return {}
    if tomllib is None:
        # Not rendered blind: the live file holds what Codex wrote for itself,
        # and without a reader there is no keeping it.
        if not quiet:
            _warn(f"codex: {CODEX_LIVE_REL} not rendered; {NO_TOML_READER}")
        return {}

    base = load_toml(base_path)
    violations = check_codex_base(base)
    if violations:
        raise ValueError(f"{CODEX_BASE_REL} must not hold: {', '.join(violations)}")

    if servers is None:
        servers = render_mcp(repo_root, write=False)
    merged = base
    mcp = codex_mcp_servers(servers, quiet)
    if mcp:
        merged = deep_merge(merged, {"mcp_servers": mcp}, markers=False)
    if fragments is None:
        fragments = collect_fragments(repo_root, CODEX_FRAGMENT_REL)
    for fragment in fragments:
        merged = deep_merge(merged, fragment, markers=False)

    managed = key_paths(merged)
    dropped = frozenset(_load_state(repo_root, CODEX_STATE_KEY) - managed)
    # Checked before the live file is read: the git call is the slowest step
    # here, and Codex may write the file while it runs.
    if write:
        _refuse_tracked_codex(repo_root)

    live_path = repo_root / CODEX_LIVE_REL
    warn = _silent if quiet else _warn
    for _ in range(CODEX_RENDER_ATTEMPTS):
        text, seen = _read_live(live_path)
        restored = None
        if text is not None:
            # A live file that does not parse is stopped on, not rendered over:
            # that would throw away whatever Codex had written there.
            live = parse_toml(text, live_path, CODEX_LIVE_HINT)
        else:
            restored = _deleted_codex_copy(repo_root)
            live = restored[1] if restored else None
        out = merged if live is None else _merge_live(live, merged, dropped, warn)
        if not write:
            return out
        # Judged on what was read, the version `seen` describes; a fresh read
        # could already hold a newer Codex write than the merge does.
        if text is not None and same_data(live, out) and _tighten(live_path):
            pass
        elif not _replace_unless_changed(live_path, dumps_toml(out, CODEX_HEADER), PRIVATE_MODE, seen):
            warn = _silent
            continue
        if restored:
            _warn(f"codex: restored {CODEX_LIVE_REL} from {restored[0][:7]}, the copy git deleted when it stopped tracking it")
        _save_state(repo_root, managed, CODEX_STATE_KEY)
        return out
    raise ValueError(
        f"{CODEX_LIVE_REL} changed during each of {CODEX_RENDER_ATTEMPTS} render attempts and "
        "was left as it is; render again once Codex is idle"
    )


_INSTRUCTION_LINE = re.compile(r"^See \[[^\]]*\]\((?:\./)?(instructions/[^)#\s]+\.md)(?:#[^)\s]*)?\)")
_BARE_TAIL = re.compile(r"^\s*[.,:;]?\s*$")
_INLINE_TARGET = re.compile(r"(\]\(\s*)(<[^>\n]*>|[^)\s]+)")
# A definition holds only a target and an optional title; "[Note]: some prose"
# is not one, and neither is a footnote ("[^1]: ...").
_REFERENCE_TARGET = re.compile(
    r"""^( {0,3}\[(?!\^)[^\]]+\]:[ \t]*)(<[^>\n]*>|\S+)(?=(?:[ \t]+(?:"[^"]*"|'[^']*'|\([^)]*\)))?[ \t]*$)"""
)
_URI_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_CODE_SPAN = re.compile(r"(`+)(?:(?!\1).)+?\1")
_FENCE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")

CODEX_AGENTS_HEADER = (
    "<!-- Rendered by scripts/render_settings.py from shared/AGENTS.md with every\n"
    "linked instructions/*.md inlined, because Codex does not follow links. Codex\n"
    "reads this in place of AGENTS.md. Edit the sources, then re-render. -->"
)


def _absolute_target(target: str, base_dir: Path) -> str:
    """A relative link target as an absolute path; URLs, anchors and absolute paths stay."""
    bracketed = target.startswith("<")
    path = target[1:-1] if bracketed else target
    if not path or path.startswith(("/", "#", "~")) or _URI_SCHEME.match(path):
        return target
    path, hash_, anchor = path.partition("#")
    path = os.path.normpath(base_dir / path) + hash_ + anchor
    return f"<{path}>" if bracketed else path


def _absolute_links(line: str, base_dir: Path) -> str:
    """Make every relative link target on the line absolute, outside code spans.

    Codex reads the render from its own home, so a relative target would point
    nowhere. Inline links and reference definitions both carry targets, with or
    without './' and with or without a title after them. Footnotes ([^1]: ...)
    and text in backticks are left as they are.
    """
    def absolute(m: re.Match) -> str:
        return m.group(1) + _absolute_target(m.group(2), base_dir)

    out, pos = [], 0
    for span in _CODE_SPAN.finditer(line):
        out.append(_INLINE_TARGET.sub(absolute, line[pos:span.start()]))
        out.append(span.group(0))
        pos = span.end()
    out.append(_INLINE_TARGET.sub(absolute, line[pos:]))
    return _REFERENCE_TARGET.sub(absolute, "".join(out))


def _fence_after(line: str, fence: str | None) -> str | None:
    """The code fence still open after `line`, or None outside a code block.

    A block closes only on a bare run of its own character at least as long as
    the one that opened it, so a ``` line inside a ~~~ or ```` block is
    content. Toggling on every fence-looking line would invert the state there.
    """
    m = _FENCE.match(line)
    if fence is None:
        # A backtick run with more backticks after it is inline code, not a fence.
        if m and not (m.group(1)[0] == "`" and "`" in m.group(2)):
            return m.group(1)
        return None
    if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) and not m.group(2).strip():
        return None
    return fence


def _prose(lines: list[str]) -> list[tuple[str, bool]]:
    """Each line with whether it is prose: neither a fence nor inside one."""
    out, fence = [], None
    for line in lines:
        before, fence = fence, _fence_after(line, fence)
        out.append((line, before is None and fence is None))
    return out


def _inline_instruction(path: Path) -> list[str]:
    """The file's body without its title, one heading level down, links made absolute."""
    lines = path.read_text().splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    while lines and not lines[0].strip():
        lines = lines[1:]
    out = []
    for line, prose in _prose(lines):
        if prose:
            if line.startswith("#"):
                line = "#" + line
            line = _absolute_links(line, path.parent)
        out.append(line)
    return out


def render_codex_agents(repo_root: Path, write: bool = True) -> str:
    """Write Codex's global instructions with the linked instruction files inlined.

    Codex reads AGENTS.override.md in place of AGENTS.md, so the tracked
    symlink stays as it is, and a checkout that has not rendered yet still
    gets instructions, only the thin ones. A link line that says more than the
    link is kept above the body, so that text is not lost; code blocks are
    copied as they are.
    """
    source = repo_root / AGENTS_SOURCE_REL
    if not source.is_file():
        return ""

    base_dir = Path(os.path.abspath(source.parent))
    out = [CODEX_AGENTS_HEADER, ""]
    for line, prose in _prose(source.read_text().splitlines()):
        match = _INSTRUCTION_LINE.match(line) if prose else None
        if match:
            target = base_dir / match.group(1)
            # personal.md and the like exist only where an overlay supplies them.
            if target.is_file():
                if not _BARE_TAIL.match(line[match.end():]):
                    out += [_absolute_links(line, base_dir), ""]
                out += _inline_instruction(target)
            continue
        out.append(_absolute_links(line, base_dir) if prose else line)

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
    """Render every artifact, and write them only once all of them have rendered.

    One source that does not parse (an overlay's settings/codex.toml with a
    typo, a codex/config.toml Codex reads but tomllib does not) used to stop the
    run after claude/settings.json and servers.json had been rewritten: Claude
    and Codex on two generations of the sources, and a caller told the render
    failed when half of it had happened. So the first pass writes nothing.
    """
    rendered = _render_each(repo_root, write=False)
    if write:
        # The checks the writing pass would otherwise make halfway through.
        if rendered[CODEX_LIVE_REL]:
            _refuse_tracked_codex(repo_root)
        for rel, value in rendered.items():
            if value:
                serialize(rel, value)
        # Quiet: the first pass has already said what it skipped.
        rendered = _render_each(repo_root, write=True, quiet=True)
    return rendered


def _render_each(repo_root: Path, write: bool, quiet: bool = False) -> dict[str, dict | str]:
    servers = render_mcp(repo_root, write=write)
    return {
        LIVE_REL: render(repo_root, write=write),
        MCP_LIVE_REL: servers,
        MEMORY_LIVE_REL: render_memory(repo_root, write=write),
        CODEX_LIVE_REL: render_codex(repo_root, servers=servers, write=write, quiet=quiet),
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


def check_bases(repo_root: Path) -> bool:
    """--check: one line per tracked base, True when none tracks a local-only key.

    A base that does not parse gets a FAIL line saying so, not a traceback
    that doctor.sh would then report as a local-only key.
    """
    bases = [(BASE_REL, load_json, check_base)]
    if (repo_root / CODEX_BASE_REL).is_file():
        bases.append((CODEX_BASE_REL, load_toml if tomllib else None, check_codex_base))
    ok = True
    for rel, load, check in bases:
        if load is None:
            print(f"SKIP  {rel} not checked; {NO_TOML_READER}")
            continue
        try:
            violations = check(load(repo_root / rel))
        except (OSError, ValueError) as exc:
            print(f"FAIL  {exc}", file=sys.stderr)
            ok = False
        else:
            if violations:
                print(f"FAIL  {rel} tracks local-only keys: {', '.join(violations)}", file=sys.stderr)
                ok = False
            else:
                print(f"OK    {rel} has no local-only keys")
    return ok


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
        return 0 if check_bases(repo_root) else 1

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
