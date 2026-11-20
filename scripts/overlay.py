#!/usr/bin/env python3
"""Manage environment overlays layered onto this repo.

Design and rationale: docs/overlay.md
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path

from install import Mkdir, Symlink
from layers import APPLY_CHECKOUT, APPLY_SYMLINK, BASE_ALIAS, OVERLAY_APPLY_MODES, VIEW_DIRS, layers
from render_settings import OVERLAYS_MODE, artifact_current, dumps, preview, render_all, substitute

OVERLAYS_REL = "overlays"
REGISTRY_REL = "overlays/registry.local.json"
APPLIED_REL = "overlays/applied.local.json"
TEMPLATE_REL = "templates/overlay-example"
MANIFEST_NAME = "overlay.json"
# Machine-only files (render fragments and variables); they must never be committed.
LOCAL_FRAGMENT_RELS = (
    "settings/claude.local.json",
    "settings/codex.local.toml",
    "mcp/servers.local.json",
    "vars.local.json",
)
VARS_NAME = "vars.json"
VARS_LOCAL_NAME = "vars.local.json"

EXCLUDE_BEGIN = "# >>> agents-overlay >>>"
EXCLUDE_END = "# <<< agents-overlay <<<"

# Checkout mode. core.worktree is relative to the clone's .git directory, so
# overlays/<alias>/.git -> ../../.. is the harness root.
CHECKOUT_WORKTREE = "../../.."
# rg and fd read .ignore (git does not), so a "!" line there makes an overlay's
# checked-out view files searchable although .git/info/exclude hides them from
# git status.
IGNORE_REL = ".ignore"
HOOK_MARKER = "# agents-overlay hook"
# git sets these for hooks; a git run aimed at another repo must not inherit them.
GIT_LOCATION_VARS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")

# (overlay dir, view dir, glob or None for directory drop-ins). The view dirs
# are where the base keeps the same parts (layers.VIEW_DIRS).
LINK_MAP = tuple(
    (src, dst, None if src == "skills" else "*.md") for src, dst in VIEW_DIRS.items()
)

ALIAS_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

# memory/MEMORY.md is the index fragment the renderer concatenates, and
# MEMORY.base.md the base's own index source: neither is a memory file to drop
# in beside the others.
LINK_SKIP = {("memory", "MEMORY.md"), ("memory", "MEMORY.base.md")}

# Setup steps an overlay cannot express as files: credentials, daemons, tokens.
DEFAULT_AGENT_TOOLS = ("Bash", "Read", "Edit", "Write", "Glob", "Grep")
AGENT_GUARDRAIL = (
    "You are completing one setup step for an agents-harness overlay, on the user's machine. "
    "Do exactly that step and nothing else. Never modify tracked files in the base harness repo, "
    "never commit or push, and never write a secret into any git repository. "
    "If the step needs a credential or a decision only the user can supply, stop and say BLOCKED "
    "with what you need. When the step is done, verify it and say DONE."
)


class OverlayError(RuntimeError):
    pass


@dataclass
class Overlay:
    alias: str
    url: str
    ref: str = "main"
    priority: int = 50
    enabled: bool = True
    repo_root: Path = field(default=Path("."), repr=False)

    is_base = False

    @property
    def path(self) -> Path:
        return self.repo_root / OVERLAYS_REL / self.alias

    @property
    def apply_mode(self) -> str:
        """How this overlay's files reach the view directories (layers.py).

        An "apply" key in the manifest decides. Without one, a clone whose
        worktree is the harness root is in checkout mode, any other symlink.
        """
        declared = self.manifest().get("apply")
        if declared:
            return declared
        return APPLY_CHECKOUT if is_checkout_clone(self) else APPLY_SYMLINK

    def real_path(self, rel: str) -> Path:
        return self.path / rel

    @property
    def cloned(self) -> bool:
        return (self.path / MANIFEST_NAME).is_file()

    def manifest(self) -> dict:
        target = self.path / MANIFEST_NAME
        return json.loads(target.read_text()) if target.is_file() else {}

    def variables(self) -> dict:
        # CLAUDE_HOME is this machine's home unless the overlay says otherwise;
        # a committed vars.json would otherwise pin every machine to the one
        # it was written on. vars.local.json is this machine's own override.
        out = {"CLAUDE_HOME": str(Path.home())}
        for name in (VARS_NAME, VARS_LOCAL_NAME):
            target = self.path / name
            if target.is_file():
                out.update(json.loads(target.read_text()))
        return out

    def as_entry(self) -> dict:
        return {
            "alias": self.alias,
            "url": self.url,
            "ref": self.ref,
            "priority": self.priority,
            "enabled": self.enabled,
        }


# ---------------------------------------------------------------------------
# Registry / applied state
# ---------------------------------------------------------------------------


def load_registry(repo_root: Path) -> list[Overlay]:
    path = repo_root / REGISTRY_REL
    if not path.is_file():
        return []
    entries = json.loads(path.read_text()).get("overlays", [])
    overlays = [
        Overlay(
            alias=e["alias"],
            url=e.get("url", ""),
            ref=e.get("ref", "main"),
            priority=int(e.get("priority", 50)),
            enabled=bool(e.get("enabled", True)),
            repo_root=repo_root,
        )
        for e in entries
    ]
    return sorted(overlays, key=lambda o: (o.priority, o.alias))


def private_overlays_dir(repo_root: Path) -> Path:
    """Create overlays/ for its owner only, or close an existing one.

    The clones under it hold what the public base must not, MCP credentials
    among them (mcp/servers.json, servers.local.json, vars.local.json), and
    git and editors write those files at the umask mode, readable by every
    user of the machine. Closing the one directory covers every file below
    it, .git included, whatever mode each file has.
    """
    path = repo_root / OVERLAYS_REL
    path.mkdir(parents=True, exist_ok=True)
    if path.stat().st_mode & 0o777 != OVERLAYS_MODE:
        os.chmod(path, OVERLAYS_MODE)
    return path


def save_registry(repo_root: Path, overlays: list[Overlay]) -> None:
    path = repo_root / REGISTRY_REL
    private_overlays_dir(repo_root)
    payload = {"overlays": [o.as_entry() for o in sorted(overlays, key=lambda o: (o.priority, o.alias))]}
    path.write_text(dumps(payload))


def enabled_overlays(repo_root: Path) -> list[Overlay]:
    return [o for o in load_registry(repo_root) if o.enabled and o.cloned]


def load_applied(repo_root: Path) -> list[dict]:
    path = repo_root / APPLIED_REL
    if not path.is_file():
        return []
    return json.loads(path.read_text()).get("links", [])


def save_applied(repo_root: Path, links: list[dict]) -> None:
    path = repo_root / APPLIED_REL
    private_overlays_dir(repo_root)
    ordered = sorted(links, key=lambda item: (item["alias"], item["link"]))
    path.write_text(dumps({"links": ordered}))


def sync_git_exclude(repo_root: Path, links: list[dict], write: bool = True) -> list[str]:
    """Keep overlay-provided symlinks out of `git status` without touching .gitignore.

    Returns the exclude lines that change, as `+/path` and `-/path`.
    """
    try:
        exclude = Path(_git(["rev-parse", "--git-path", "info/exclude"], cwd=repo_root))
    except OverlayError:
        return []
    if not exclude.is_absolute():
        exclude = repo_root / exclude
    current = exclude.read_text().splitlines() if exclude.is_file() else []

    kept: list[str] = []
    ours: set[str] = set()
    skipping = False
    for line in current:
        if line.strip() == EXCLUDE_BEGIN:
            skipping = True
            continue
        if line.strip() == EXCLUDE_END:
            skipping = False
            continue
        if skipping:
            ours.add(line.strip())
        else:
            kept.append(line)

    while kept and not kept[-1].strip():
        kept.pop()

    wanted = {f"/{item['link']}" for item in links}
    if any(item.get("mode") == APPLY_CHECKOUT for item in links):
        wanted.add(f"/{IGNORE_REL}")
    if write:
        block = [EXCLUDE_BEGIN] + sorted(wanted) + [EXCLUDE_END]
        body = kept + ([""] if kept else []) + (block if links else [])
        exclude.parent.mkdir(parents=True, exist_ok=True)
        exclude.write_text("\n".join(body).rstrip("\n") + "\n")
    return [f"+{line}" for line in sorted(wanted - ours)] + [f"-{line}" for line in sorted(ours - wanted)]


def sync_ignore_file(repo_root: Path, links: list[dict], write: bool = True) -> None:
    """Keep checkout overlays' view files searchable by rg and fd.

    git excludes them through .git/info/exclude, and rg and fd honour that, so
    a marked block in .ignore (which git never reads) re-includes each one.
    Lines outside the block are the user's and are left alone.
    """
    units = sorted(item["link"] for item in links if item.get("mode") == APPLY_CHECKOUT)
    path = repo_root / IGNORE_REL
    current = path.read_text().splitlines() if path.is_file() else []
    kept: list[str] = []
    skipping = False
    for line in current:
        if line.strip() == EXCLUDE_BEGIN:
            skipping = True
        elif line.strip() == EXCLUDE_END:
            skipping = False
        elif not skipping:
            kept.append(line)
    while kept and not kept[-1].strip():
        kept.pop()

    block: list[str] = []
    if units:
        block = [EXCLUDE_BEGIN, "# checked-out view files of overlays (scripts/overlay.py); git excludes them"]
        block += [f"!/{unit}/" if (repo_root / unit).is_dir() else f"!/{unit}" for unit in units]
        block.append(EXCLUDE_END)
    if not write:
        return
    body = kept + ([""] if kept and block else []) + block
    if body:
        text = "\n".join(body) + "\n"
        if not path.is_file() or path.read_text() != text:
            path.write_text(text)
    elif path.is_file():
        path.unlink()


# ---------------------------------------------------------------------------
# Checkout mode
# ---------------------------------------------------------------------------


def is_checkout_clone(overlay) -> bool:
    """True when the clone's worktree is the harness root (checkout mode)."""
    if not (overlay.path / ".git").exists():
        return False
    try:
        top = _git(["rev-parse", "--show-toplevel"], cwd=overlay.path)
    except OverlayError:
        return False
    return Path(top).resolve() == overlay.repo_root.resolve()


def _view_overlay_rel(view_rel: str) -> str | None:
    """shared/memory/x.md -> memory/x.md: where symlink mode keeps a view path."""
    for src, dst, _pattern in LINK_MAP:
        if view_rel.startswith(dst + "/"):
            return src + view_rel[len(dst):]
    return None


def _view_unit(rel: str) -> str | None:
    """The unit a tracked path belongs to: the .md file itself, or the skill directory."""
    for src, dst, pattern in LINK_MAP:
        prefix = dst + "/"
        if not rel.startswith(prefix):
            continue
        rest = rel[len(prefix):]
        if pattern is None:
            return prefix + rest.split("/", 1)[0] if "/" in rest else None
        if "/" not in rest and fnmatch(rest, pattern) and (src, rest) not in LINK_SKIP:
            return rel
        return None
    return None


def _overlay_tracked(overlay, rev: str | None = None) -> list[str]:
    """Paths the overlay tracks, relative to its worktree root."""
    if rev:
        out = _git(["ls-tree", "-r", "-z", "--name-only", "--full-tree", rev], cwd=overlay.path)
    else:
        out = _git(["ls-files", "-z", "--full-name", "--", ":/"], cwd=overlay.path)
    return [rel for rel in out.split("\0") if rel]


def owned_view_units(overlay, rev: str | None = None) -> list[str]:
    """View paths a checkout overlay provides: each .md file, each skill directory."""
    return sorted({unit for rel in _overlay_tracked(overlay, rev) if (unit := _view_unit(rel))})


def _foreign_paths(overlay, rev: str | None = None) -> list[str]:
    """Tracked paths a checkout overlay has no business holding."""
    own = f"{OVERLAYS_REL}/{overlay.alias}/"
    views = tuple(dst + "/" for _src, dst, _pattern in LINK_MAP)
    return [rel for rel in _overlay_tracked(overlay, rev) if not rel.startswith(own) and not rel.startswith(views)]


def _base_tracked(repo_root: Path, units: list[str]) -> set[str]:
    """The units (files or directories) the harness repo itself tracks."""
    if not units:
        return set()
    try:
        out = _git(["ls-files", "-z", "--", *units], cwd=repo_root)
    except OverlayError:
        return set()  # not a git checkout (a fixture, a bare copy): nothing tracked
    tracked = [rel for rel in out.split("\0") if rel]
    return {unit for unit in units if any(rel == unit or rel.startswith(unit + "/") for rel in tracked)}


def _git_at_root(overlay, args: list[str]) -> str:
    """Run the overlay's git from the harness root, so pathspecs and -a cover the whole worktree.

    Plumbing such as checkout-index limits itself to the current directory, and
    a checkout overlay's clone directory is only one corner of its worktree.
    """
    gitdir = overlay.path / ".git"
    return _git([f"--git-dir={gitdir}", f"--work-tree={overlay.repo_root}", *args], cwd=overlay.repo_root)


def _tree_has(overlay, rev: str, rel: str) -> bool:
    try:
        _git(["cat-file", "-e", f"{rev}:{rel}"], cwd=overlay.path)
    except OverlayError:
        return False
    return True


def _guard_hook(alias: str) -> str:
    views = "|".join(f"{dst}/*" for _src, dst, _pattern in LINK_MAP)
    return f"""#!/bin/sh
{HOOK_MARKER}: written by scripts/overlay.py, do not edit by hand.
# This overlay's worktree is the harness root. Refuse a commit that takes in a
# file outside the overlay's own paths, or one the harness repo itself tracks.
root=$(git rev-parse --show-toplevel) || exit 1
git diff --cached --name-only --no-renames --diff-filter=ACMRT -z | tr '\\0' '\\n' | {{
  bad=0
  while IFS= read -r p; do
    case "$p" in
      {OVERLAYS_REL}/{alias}/*|{views}) ;;
      *) echo "overlay guard: $p is outside overlay '{alias}' and the view directories" >&2; bad=1; continue ;;
    esac
    if env -u GIT_DIR -u GIT_WORK_TREE -u GIT_INDEX_FILE git -C "$root" ls-files --error-unmatch -- "$p" >/dev/null 2>&1; then
      echo "overlay guard: $p is tracked by the harness repo, so it cannot belong to overlay '{alias}'" >&2; bad=1
    fi
  done
  exit $bad
}}
"""


def _sync_hook() -> str:
    return f"""#!/bin/sh
{HOOK_MARKER}: written by scripts/overlay.py, do not edit by hand.
# Keep the harness repo's exclude list and .ignore in step with the view files
# this overlay tracks, so a newly committed one never shows as untracked there.
root=$(git rev-parse --show-toplevel) || exit 0
env -u GIT_DIR -u GIT_WORK_TREE -u GIT_INDEX_FILE python3 "$root/scripts/overlay.py" sync-views >/dev/null 2>&1 || true
"""


def _hook_texts(overlay) -> dict[str, str]:
    sync = _sync_hook()
    return {"pre-commit": _guard_hook(overlay.alias), "post-commit": sync, "post-merge": sync}


def _hooks_dir(overlay) -> Path:
    return Path(_git(["rev-parse", "--path-format=absolute", "--git-path", "hooks"], cwd=overlay.path))


def hooks_current(overlay) -> bool:
    hooks = _hooks_dir(overlay)
    return all((hooks / name).is_file() and (hooks / name).read_text() == text for name, text in _hook_texts(overlay).items())


def install_hooks(overlay) -> None:
    """The guard and sync hooks a checkout overlay needs; someone else's hook is never overwritten."""
    hooks = _hooks_dir(overlay)
    hooks.mkdir(parents=True, exist_ok=True)
    for name, text in _hook_texts(overlay).items():
        target = hooks / name
        if target.exists() and HOOK_MARKER not in target.read_text(errors="replace"):
            raise OverlayError(f"{overlay.alias}: {target} is not ours; move it aside and rerun")
        if not target.is_file() or target.read_text() != text:
            target.write_text(text)
            os.chmod(target, 0o755)


def unfiled_paths(repo_root: Path) -> list[str]:
    """What sits in the view dirs with no repo tracking it.

    Overlay links and checkout overlays' files are excluded from the base, so
    whatever git still calls untracked there belongs to nobody yet: a skill
    directory, a memory file, or a loose file inside a skill the base owns.
    """
    try:
        out = _git(["ls-files", "-z", "--others", "--exclude-standard", "--", *VIEW_DIRS.values()], cwd=repo_root)
    except OverlayError:
        return []
    rels = [rel for rel in out.split("\0") if rel]
    units = {unit for rel in rels if (unit := _view_unit(rel))}
    based = _base_tracked(repo_root, sorted(units))
    found = {unit for unit in units if unit not in based}
    found |= {rel for rel in rels if _view_unit(rel) in based}
    return sorted(found)


BASE_GUARD_HOOK = f"""#!/bin/sh
{HOOK_MARKER}: written by scripts/overlay.py, do not edit by hand.
# Refuse a commit to this (public) repo that takes in a file an overlay provides.
script="$(git rev-parse --show-toplevel)/scripts/overlay.py"
[ -f "$script" ] || exit 0
exec python3 "$script" check-staged
"""


def install_base_hook(repo_root: Path, log) -> None:
    try:
        hooks = Path(_git(["rev-parse", "--path-format=absolute", "--git-path", "hooks"], cwd=repo_root))
    except OverlayError:
        return  # not a git checkout
    target = hooks / "pre-commit"
    if target.exists() and HOOK_MARKER not in target.read_text(errors="replace"):
        log(f"WARN  {target} is not ours, so the base commit guard is not installed")
        return
    if not target.is_file() or target.read_text() != BASE_GUARD_HOOK:
        hooks.mkdir(parents=True, exist_ok=True)
        target.write_text(BASE_GUARD_HOOK)
        os.chmod(target, 0o755)


def _owner(applied: list[dict], rel: str) -> str | None:
    for item in applied:
        if rel == item["link"] or rel.startswith(item["link"].rstrip("/") + "/"):
            return item["alias"]
    return None


def cmd_check_staged(repo_root: Path, args, log) -> int:
    """The base's pre-commit guard: no file an overlay provides may enter the base."""
    # Inherit the environment on purpose: a hook gets GIT_INDEX_FILE for the
    # index being committed, which differs from .git/index for `commit <paths>`.
    proc = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--no-renames", "--diff-filter=ACMRT", "-z"],
        cwd=str(repo_root), capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return 0
    applied = load_applied(repo_root)
    clones = [f"{OVERLAYS_REL}/{o.alias}/" for o in load_registry(repo_root)]
    bad = 0
    for rel in filter(None, proc.stdout.split("\0")):
        alias = _owner(applied, rel) or next((c.split("/")[1] for c in clones if rel.startswith(c)), None)
        if alias:
            print(f"base guard: {rel} is provided by overlay '{alias}'; commit it there", file=sys.stderr)
            bad = 1
    return bad


def _move_index_line(repo_root: Path, unit: str, target: Path, log) -> None:
    """Move a memory's index line from the rendered index to the source that now owns it."""
    from render_settings import MEMORY_BASE_REL, MEMORY_LIVE_REL

    name = Path(unit).name
    marker = f"]({name})"
    sources = [repo_root / MEMORY_BASE_REL] + [o.path / "memory" / "MEMORY.md" for o in enabled_overlays(repo_root)]
    if any(marker in source.read_text() for source in sources if source.is_file()):
        log(f"KEEP  the index line for {name} (already in an index source)")
        return
    live = repo_root / MEMORY_LIVE_REL
    lines = [line for line in (live.read_text().splitlines() if live.is_file() else []) if marker in line]
    if not lines:
        log(f"NOTE  no index line for {name} yet; add one to {target.relative_to(repo_root)}")
        return
    text = target.read_text() if target.is_file() else ""
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text((text.rstrip("\n") + "\n" if text.strip() else "") + lines[0] + "\n")
    log(f"INDEX {name}: line moved to {target.relative_to(repo_root)}")


def cmd_file(repo_root: Path, args, log) -> int:
    """Give an unfiled view file its owner: stage it in the base or an overlay, and move its index line."""
    from render_settings import MEMORY_BASE_REL

    raw = Path(args.path).expanduser()
    absolute = (raw if raw.is_absolute() else Path.cwd() / raw).resolve()
    rel = os.path.relpath(absolute, repo_root.resolve())
    if rel not in unfiled_paths(repo_root):
        unit = _view_unit(rel)
        if unit and unit in unfiled_paths(repo_root):
            rel = unit  # a file inside an unfiled skill: file the whole skill
        else:
            raise OverlayError(f"{rel} is not an unfiled view file (see 'overlay.py status')")

    if args.to == BASE_ALIAS:
        _git(["add", "--", rel], cwd=repo_root)
        index = repo_root / MEMORY_BASE_REL
        where = "the base repo"
    else:
        overlay = next((o for o in enabled_overlays(repo_root) if o.alias == args.to), None)
        if overlay is None:
            raise OverlayError(f"no enabled overlay registered as '{args.to}'")
        if not _view_unit(rel) == rel:
            raise OverlayError(f"{rel} sits inside a skill the base owns; only the base can take it")
        if overlay.apply_mode == APPLY_CHECKOUT:
            _git_at_root(overlay, ["add", "--", rel])
        else:
            inside = _view_overlay_rel(rel)
            dest = overlay.path / inside
            if dest.exists() or dest.is_symlink():
                raise OverlayError(f"{overlay.alias} already has {inside}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.replace(repo_root / rel, dest)  # install links it back below
            _git(["add", "--", inside], cwd=overlay.path)
        index = overlay.path / "memory" / "MEMORY.md"
        where = f"overlay '{overlay.alias}' ({overlay.path.relative_to(repo_root)})"
    log(f"STAGE {rel} in {where}")

    if rel.startswith(VIEW_DIRS["memory"] + "/"):
        _move_index_line(repo_root, rel, index, log)

    applied = load_applied(repo_root)
    for overlay in enabled_overlays(repo_root):
        applied = apply_overlay(repo_root, overlay, applied, lambda _msg: None)
    save_applied(repo_root, applied)
    sync_git_exclude(repo_root, applied)
    sync_ignore_file(repo_root, applied)
    _render(repo_root)
    log(f"next: review and commit it in {where}")
    return 0


def _checkout_items(repo_root: Path, overlay, others: dict[str, str]) -> list[dict]:
    """Applied records for a checkout overlay's view files, after refusing every conflict."""
    if not is_checkout_clone(overlay):
        raise OverlayError(
            f"{overlay.alias}: apply mode is checkout but the clone is not checked out in place — "
            f"run 'overlay.py convert {overlay.alias}'"
        )
    foreign = _foreign_paths(overlay)
    if foreign:
        raise OverlayError(f"{overlay.alias}: tracks paths outside its own and the view dirs: {', '.join(foreign[:5])}")
    units = owned_view_units(overlay)
    conflicts = [f"{unit} (overlay '{others[unit]}' already provides it)" for unit in units if unit in others]
    conflicts += [f"{unit} (base repo already has it)" for unit in sorted(_base_tracked(repo_root, units))]
    conflicts += [f"{unit} (a symlink is in the way)" for unit in units if (repo_root / unit).is_symlink()]
    if conflicts:
        raise OverlayError(f"{overlay.alias}: refusing to apply —\n  " + "\n  ".join(conflicts))
    return [{"alias": overlay.alias, "link": unit, "source": unit, "mode": APPLY_CHECKOUT} for unit in units]


# ---------------------------------------------------------------------------
# Apply / unapply
# ---------------------------------------------------------------------------


def _planned_links(overlay: Overlay) -> list[tuple[Path, Path]]:
    """(source, target) pairs this overlay contributes, both absolute.

    In checkout mode the view files are already in place, so only the
    manifest's `links` are symlinked.
    """
    pairs: list[tuple[Path, Path]] = []
    for src_rel, dst_rel, pattern in (LINK_MAP if overlay.apply_mode != APPLY_CHECKOUT else ()):
        src_dir = overlay.path / src_rel
        if not src_dir.is_dir():
            continue
        dst_dir = overlay.repo_root / dst_rel
        items = sorted(src_dir.glob(pattern)) if pattern else sorted(p for p in src_dir.iterdir() if p.is_dir())
        for item in items:
            if (src_rel, item.name) in LINK_SKIP:
                continue
            pairs.append((item, dst_dir / item.name))

    # Escape hatch for anything the fixed namespaces don't cover. An overlay is
    # a repo someone else may have written, so both ends are checked: it may
    # only publish its own files, and only into this repo.
    for src_rel, dst_rel in overlay.manifest().get("links", {}).items():
        source = overlay.path / src_rel
        if not _inside(source, overlay.path):
            raise OverlayError(f"{overlay.alias}: links source '{src_rel}' escapes the overlay")
        if not source.exists():
            raise OverlayError(f"{overlay.alias}: links entry '{src_rel}' does not exist in the overlay")
        target = overlay.repo_root / dst_rel
        if not _inside(target, overlay.repo_root):
            raise OverlayError(f"{overlay.alias}: links target '{dst_rel}' escapes the repo")
        pairs.append((source, target))
    return pairs


def _inside(path: Path, root: Path) -> bool:
    try:
        resolved = Path(os.path.normpath(str(path)))
        root_resolved = Path(os.path.normpath(str(root)))
        return resolved == root_resolved or root_resolved in resolved.parents
    except (OSError, ValueError):
        return False


def _relative_symlink(source: Path, target: Path) -> Path:
    return Path(os.path.relpath(source, target.parent))


def apply_overlay(
    repo_root: Path, overlay: Overlay, applied: list[dict], log, dry_run: bool = False
) -> list[dict]:
    """Link the overlay's files in; returns the applied list as it is afterwards.

    A dry run touches nothing, logs only the links that would change, and
    returns the list a real run would.
    """
    if not overlay.cloned:
        raise OverlayError(f"{overlay.alias}: not cloned — run 'overlay.py add' first")
    mode = overlay.apply_mode
    if mode not in OVERLAY_APPLY_MODES:
        raise OverlayError(
            f"{overlay.alias}: unknown apply mode '{mode}' in {MANIFEST_NAME} "
            f"(supported: {', '.join(OVERLAY_APPLY_MODES)})"
        )

    mine = {item["link"] for item in applied if item["alias"] == overlay.alias}
    others = {item["link"]: item["alias"] for item in applied if item["alias"] != overlay.alias}
    in_place_files = {item["link"] for item in applied if item.get("mode") == APPLY_CHECKOUT}
    ranks = {o.alias: _rank(o) for o in load_registry(repo_root)}

    # A checkout overlay's view files are already where they belong; record
    # them (after refusing any conflict) and link only its manifest `links`.
    checkout_items = _checkout_items(repo_root, overlay, others) if mode == APPLY_CHECKOUT else []
    if dry_run:
        for item in checkout_items:
            if item["link"] not in mine:
                log(f"VIEW  {item['link']} (checked out in place by '{overlay.alias}')")

    planned = _planned_links(overlay)
    conflicts = []
    deferred: dict[str, str] = {}   # link -> the overlay that outranks us
    takeovers: dict[str, str] = {}  # link -> the overlay we outrank
    for source, target in planned:
        rel = str(target.relative_to(repo_root))
        if rel in others and rel in in_place_files:
            # A real file another overlay tracks in place: priority cannot move it.
            conflicts.append(f"{rel} (overlay '{others[rel]}' keeps its own file there)")
        elif rel in others:
            # Two overlays want the same path. Priority decides it, exactly as
            # it decides a shared JSON key — not whoever happened to install
            # first. Ties break on alias, matching the render order.
            holder = others[rel]
            if ranks.get(holder, (0, holder)) > ranks.get(overlay.alias, _rank(overlay)):
                deferred[rel] = holder
            else:
                takeovers[rel] = holder
        elif (target.exists() or target.is_symlink()) and rel not in mine:
            if not (target.is_symlink() and target.resolve() == source.resolve()):
                conflicts.append(f"{rel} (base repo already has it)")
    if conflicts:
        raise OverlayError(f"{overlay.alias}: refusing to apply —\n  " + "\n  ".join(conflicts))

    for rel, holder in sorted(deferred.items()):
        log(f"DEFER {rel} stays with '{holder}' (higher priority)")
    for rel, holder in sorted(takeovers.items()):
        log(f"TAKE  {rel} from '{holder}' (lower priority)")
        applied = [
            item for item in applied
            if not (item["alias"] == holder and item["link"] == rel)
        ]
        others.pop(rel, None)
        if not dry_run:
            _unlink(repo_root / rel, lambda _msg: None)

    planned = [
        (source, target)
        for source, target in planned
        if str(target.relative_to(repo_root)) not in deferred
    ]

    links = [item for item in applied if item["alias"] != overlay.alias] + checkout_items
    if checkout_items and not dry_run:
        install_hooks(overlay)
    in_place = 0
    for source, target in planned:
        rel_source = _relative_symlink(source, target)
        if dry_run:
            if target.is_symlink() and Path(os.readlink(target)) == rel_source:
                in_place += 1
            else:
                log(f"LINK  {target.relative_to(repo_root)} -> {rel_source}")
        else:
            if target.is_symlink():
                target.unlink()
            Mkdir(target.parent).apply()
            Symlink(rel_source, target).apply()
            log(f"LINK  {target.relative_to(repo_root)} -> {rel_source}")
        links.append(
            {
                "alias": overlay.alias,
                "link": str(target.relative_to(repo_root)),
                "source": str(source.relative_to(repo_root)),
            }
        )

    # Links the overlay used to provide but no longer does.
    still = {item["link"] for item in links if item["alias"] == overlay.alias}
    for stale in sorted(mine - still):
        if not dry_run:
            _unlink(repo_root / stale, log)
        elif (repo_root / stale).is_symlink():
            log(f"UNLINK {repo_root / stale}")

    if in_place:
        log(f"KEEP  {in_place} link(s) of '{overlay.alias}' already in place")
    if checkout_items:
        log(f"KEEP  {len(checkout_items)} view file(s) of '{overlay.alias}' checked out in place")
    return links


def _rank(overlay: Overlay) -> tuple[int, str]:
    """Who wins a contested path or key: higher priority, then later alias."""
    return (overlay.priority, overlay.alias)


def _unlink(target: Path, log) -> None:
    if target.is_symlink():
        target.unlink()
        log(f"UNLINK {target}")


def unapply_overlay(repo_root: Path, alias: str, applied: list[dict], log) -> list[dict]:
    for item in applied:
        if item["alias"] == alias:
            _unlink(repo_root / item["link"], log)
    return [item for item in applied if item["alias"] != alias]


# ---------------------------------------------------------------------------
# git helpers
# ---------------------------------------------------------------------------


def _git(args: list[str], cwd: Path | None = None) -> str:
    # Always located by cwd: a GIT_DIR inherited from a hook would aim it at
    # another repo, and a checkout overlay shares its worktree with the base.
    env = {k: v for k, v in os.environ.items() if k not in GIT_LOCATION_VARS}
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        env=env,
    )
    if proc.returncode != 0:
        raise OverlayError(f"git {' '.join(args)} failed:\n{proc.stderr.strip()}")
    return proc.stdout.strip()


def _render(repo_root: Path, write: bool = True) -> dict[str, dict | str]:
    """render_all, with a source that does not parse reported as an OverlayError.

    That is a typo in one of the user's own files, so it gets one line naming
    the file rather than a traceback. render_all has written nothing by then.
    """
    try:
        return render_all(repo_root, write=write)
    except ValueError as exc:
        raise OverlayError(f"render failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_add(repo_root: Path, args, log) -> int:
    if not ALIAS_RE.match(args.alias):
        raise OverlayError(f"invalid alias '{args.alias}' (use lowercase letters, digits, - and _)")
    if args.alias == BASE_ALIAS:
        raise OverlayError(f"alias '{BASE_ALIAS}' is reserved for the harness repo itself (layer 0)")

    overlays = load_registry(repo_root)
    if any(o.alias == args.alias for o in overlays):
        raise OverlayError(f"alias '{args.alias}' is already registered")

    entry = Overlay(
        alias=args.alias,
        url=args.url or "",
        ref=args.ref,
        priority=args.priority if args.priority is not None else 50,
        repo_root=repo_root,
    )

    if entry.path.exists():
        # The clone is already in place — the authoring machine, or a checkout
        # the user put there by hand. Register it instead of cloning over it.
        if not entry.cloned:
            raise OverlayError(f"{entry.path} exists but has no {MANIFEST_NAME}")
        try:
            origin = _git(["remote", "get-url", "origin"], cwd=entry.path)
        except OverlayError:
            origin = ""  # scaffolded locally and not pushed anywhere yet
        if args.url and origin and args.url != origin:
            raise OverlayError(
                f"{entry.path} already tracks {origin}, not {args.url} — "
                "move it aside or drop the url argument"
            )
        entry.url = args.url or origin
        entry.ref = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=entry.path)
        log(f"FOUND {entry.path} ({entry.url or 'no remote yet'} @ {entry.ref})")
    else:
        if not args.url:
            raise OverlayError(f"nothing at {entry.path} — pass a git url to clone")
        private_overlays_dir(repo_root)
        clone = ["clone", "--no-checkout", "--branch", args.ref, args.url, str(entry.path)]
        log(f"RUN   git {' '.join(clone)}")
        _git(clone)
        try:
            _checkout_fresh_clone(repo_root, entry, log)
        except OverlayError:
            shutil.rmtree(entry.path, ignore_errors=True)  # our own clone, made a moment ago
            raise
        if not entry.cloned:
            shutil.rmtree(entry.path, ignore_errors=True)
            raise OverlayError(f"{args.url} has no {MANIFEST_NAME} — not an overlay repo")

    # Without --priority the overlay's own manifest decides, as documented.
    if args.priority is None:
        declared = entry.manifest().get("priority", 50)
        if isinstance(declared, bool) or not isinstance(declared, int):
            raise OverlayError(
                f"{entry.path / MANIFEST_NAME}: priority must be an integer, got {declared!r} — "
                f"fix it or pass --priority, then rerun 'overlay.py add {args.alias}'"
            )
        entry.priority = declared

    overlays.append(entry)
    save_registry(repo_root, overlays)
    log(f"added '{args.alias}' (priority {entry.priority}). Run 'overlay.py install {args.alias}' to apply.")
    return 0


def _checkout_fresh_clone(repo_root: Path, overlay: Overlay, log) -> None:
    """Fill a `clone --no-checkout`: in place at the harness root for a checkout-layout repo.

    A checkout-layout repo keeps its manifest at overlays/<alias>/overlay.json.
    Its view files go straight into the view dirs, so every one is checked
    against the base and the disk first, and checkout-index writes only
    missing files: nothing the base has can be overwritten.
    """
    if not _tree_has(overlay, "HEAD", f"{OVERLAYS_REL}/{overlay.alias}/{MANIFEST_NAME}"):
        _git(["read-tree", "HEAD"], cwd=overlay.path)
        _git(["checkout-index", "-a"], cwd=overlay.path)
        return

    foreign = _foreign_paths(overlay, "HEAD")
    if foreign:
        raise OverlayError(f"{overlay.alias}: tracks paths outside its own and the view dirs: {', '.join(foreign[:5])}")
    units = owned_view_units(overlay, "HEAD")
    clash = sorted(_base_tracked(repo_root, units))
    clash += [unit for unit in units if (repo_root / unit).exists() or (repo_root / unit).is_symlink()]
    if clash:
        raise OverlayError(f"{overlay.alias}: refusing to check out over existing paths: {', '.join(sorted(set(clash)))}")
    _git(["config", "core.worktree", CHECKOUT_WORKTREE], cwd=overlay.path)
    _git(["config", "status.showUntrackedFiles", "no"], cwd=overlay.path)
    _git(["read-tree", "HEAD"], cwd=overlay.path)
    _git_at_root(overlay, ["checkout-index", "-a"])
    _git(["update-index", "-q", "--refresh"], cwd=overlay.path)
    install_hooks(overlay)
    log(f"CHECKOUT {overlay.alias} in place: {len(units)} view file(s) under the harness root")


def cmd_install(repo_root: Path, args, log) -> int:
    overlays = load_registry(repo_root)
    if args.alias:
        overlays = [o for o in overlays if o.alias == args.alias]
        if not overlays:
            raise OverlayError(f"no overlay registered as '{args.alias}'")
    else:
        overlays = [o for o in overlays if o.enabled]

    dry_run = getattr(args, "dry_run", False)
    before = load_applied(repo_root)
    applied = before
    for overlay in overlays:
        applied = apply_overlay(repo_root, overlay, applied, log, dry_run=dry_run)

    if dry_run:
        for line in sync_git_exclude(repo_root, applied, write=False):
            log(f"EXCLUDE {line}")
        moved = {(i["link"], i["source"]) for i in before} ^ {(i["link"], i["source"]) for i in applied}
        if any(link.startswith("shared/instructions/") for link, _ in moved):
            log("NOTE  codex/AGENTS.override.md below inlines shared/instructions/ as linked now, before these links change")
        for line in preview(repo_root, _render(repo_root, write=False)):
            log(f"RENDER {line}")
    else:
        save_applied(repo_root, applied)
        sync_git_exclude(repo_root, applied)
        sync_ignore_file(repo_root, applied)
        install_base_hook(repo_root, log)
        for rel, merged in _render(repo_root).items():
            if merged:
                log(f"RENDER {rel} (base + {len(enabled_overlays(repo_root))} overlay(s))")
    # The render just read these, so this is when a machine-only file the
    # overlay's git would pick up is worth saying — before anything commits it.
    for overlay in enabled_overlays(repo_root):
        for rel in unignored_local_files(overlay):
            log(f"WARN {_unignored_hint(overlay, rel)}")
    if dry_run:
        log("dry run: nothing was changed; run it again without --dry-run to apply")
    return 0


def unignored_local_files(overlay: Overlay) -> list[str]:
    """LOCAL_FRAGMENT_RELS present in the overlay that its git does not ignore.

    An overlay scaffolded before a pattern reached the template's .gitignore
    (*.local.toml came after *.local.json) ignores only the older one, and
    `git add -A` there commits the file along with whatever token it holds.
    A file git already tracks is never ignored, whatever the .gitignore says.
    """
    found = []
    for rel in LOCAL_FRAGMENT_RELS:
        if not (overlay.path / rel).is_file():
            continue
        ignored = subprocess.run(
            ["git", "check-ignore", "-q", rel], cwd=str(overlay.path), capture_output=True
        )
        if ignored.returncode != 0:
            found.append(rel)
    return found


def _unignored_hint(overlay: Overlay, rel: str) -> str:
    return (
        f"{overlay.alias}/{rel} is not gitignored — add '*.local.json' and '*.local.toml' "
        "to the overlay's .gitignore so it stays on this machine, and 'git rm --cached' "
        "it there if git already tracks it"
    )


def cmd_list(repo_root: Path, args, log) -> int:
    overlays = load_registry(repo_root)
    if not overlays:
        log("no overlays registered")
        return 0

    applied = load_applied(repo_root)
    counts: dict[str, int] = {}
    for item in applied:
        counts[item["alias"]] = counts.get(item["alias"], 0) + 1

    log(f"{'ALIAS':<16} {'PRIO':>4}  {'MODE':<8} {'STATE':<12} {'LINKS':>5}  REF     URL")
    log(f"{BASE_ALIAS:<16} {0:>4}  {'inplace':<8} {'base':<12} {'-':>5}  {'-':<7} this repo (layer 0, layer.json)")
    for overlay in overlays:
        if not overlay.cloned:
            state = "not-cloned"
        elif not overlay.enabled:
            state = "disabled"
        elif overlay.alias in counts:
            state = "applied"
        else:
            state = "registered"
        mode = overlay.apply_mode if overlay.cloned else "-"
        log(
            f"{overlay.alias:<16} {overlay.priority:>4}  {mode:<8} {state:<12} "
            f"{counts.get(overlay.alias, 0):>5}  {overlay.ref:<7} {overlay.url}"
        )
    return 0


def cmd_status(repo_root: Path, args, log) -> int:
    problems = 0
    applied = load_applied(repo_root)

    for item in applied:
        link = repo_root / item["link"]
        source = repo_root / item["source"]
        if item.get("mode") == APPLY_CHECKOUT:
            # The overlay's own file, tracked in place: it must be a real file.
            if link.is_symlink():
                log(f"DRIFT {item['link']} is a symlink, expected the file overlay '{item['alias']}' tracks")
                problems += 1
            elif not link.exists():
                log(f"DRIFT {item['link']} is missing (overlay '{item['alias']}' tracks it)")
                problems += 1
            continue
        if not link.is_symlink():
            log(f"DRIFT {item['link']} is not a symlink ({item['alias']})")
            problems += 1
        elif not link.exists():
            log(f"DRIFT {item['link']} is dangling -> {os.readlink(link)}")
            problems += 1
        elif link.resolve() != source.resolve():
            log(f"DRIFT {item['link']} points at {os.readlink(link)}, expected {item['source']}")
            problems += 1

    for overlay in load_registry(repo_root):
        if overlay.cloned and _git(["status", "--porcelain"], cwd=overlay.path):
            log(f"DIRTY {overlay.alias} has uncommitted changes in {overlay.path}")
            problems += 1
        if overlay.cloned and overlay.enabled and overlay.apply_mode == APPLY_CHECKOUT:
            if not is_checkout_clone(overlay):
                log(f"DRIFT {overlay.alias} says checkout but is not checked out in place — run 'overlay.py convert {overlay.alias}'")
                problems += 1
            elif not hooks_current(overlay):
                log(f"DRIFT {overlay.alias} is missing its guard or sync hooks — run 'overlay.py install {overlay.alias}'")
                problems += 1
        for rel in unignored_local_files(overlay):
            log(f"LOCAL {_unignored_hint(overlay, rel)}")
            problems += 1

    if (repo_root / "claude" / "settings.base.json").is_file():
        try:
            rendered = render_all(repo_root, write=False)
        except ValueError as exc:
            # Reported like any other problem, so the checks below still run.
            log(f"RENDER {exc}")
            problems += 1
            rendered = {}
        for rel, merged in rendered.items():
            if merged and not artifact_current(repo_root, rel, merged):
                log(f"DRIFT {rel} differs from a fresh render — run 'overlay.py install'")
                problems += 1

    for layer in layers(repo_root):
        for step in layer.manifest().get("setup", []):
            if _run_check(repo_root, layer, step) is False:
                log(f"SETUP {layer.alias}/{step['id']} pending — run 'overlay.py setup {layer.alias}'")
                problems += 1

    for rel in unfiled_paths(repo_root):
        log(f"UNFILED {rel} — no repo tracks it; 'overlay.py file {rel} --to base|<overlay>'")
        problems += 1

    if problems == 0:
        log(f"overlay: clean ({len(applied)} link(s))")
    return 1 if problems else 0


# The setup helpers below take any layer: an Overlay or layers.BaseLayer.


def _step_env(overlay) -> dict:
    env = dict(os.environ)
    env.update({k: str(v) for k, v in overlay.variables().items()})
    return env


def _run_check(repo_root: Path, overlay, step: dict) -> bool | None:
    """True = already satisfied, False = pending, None = step declares no check."""
    command = step.get("check")
    if not command:
        return None
    proc = subprocess.run(
        ["bash", "-c", command],
        cwd=str(repo_root),
        env=_step_env(overlay),
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def _agent_command(repo_root: Path, overlay, step: dict, args) -> list[str]:
    if overlay.is_base:
        # The guardrail tells the agent never to touch the base repo's tracked
        # files, so a base step has to be a plain command or a manual one.
        raise OverlayError(f"{overlay.alias}/{step['id']}: base setup steps cannot be agent steps")
    prompt_path = overlay.path / step["agent"]
    if not prompt_path.is_file():
        raise OverlayError(f"{overlay.alias}/{step['id']}: agent prompt missing: {step['agent']}")
    prompt = substitute(prompt_path.read_text(), overlay.variables())
    tools = list(step.get("allowedTools") or DEFAULT_AGENT_TOOLS)

    cmd = ["claude"]
    if not args.interactive:
        cmd += ["-p", "--output-format", "json"]
    cmd += [
        "--permission-mode", args.permission_mode,
        "--add-dir", str(overlay.path),
        "--allowedTools", *tools,
        "--append-system-prompt", AGENT_GUARDRAIL,
    ]
    if args.model:
        cmd += ["--model", args.model]
    return cmd + [prompt]


def _run_step(repo_root: Path, overlay, step: dict, args, log) -> str:
    label = f"{overlay.alias}/{step['id']}"

    if step.get("run"):
        log(f"RUN   {label}: {step['run']}")
        proc = subprocess.run(
            ["bash", "-c", step["run"]],
            cwd=str(repo_root),
            env=_step_env(overlay),
        )
        if proc.returncode != 0:
            return "failed"
    elif step.get("agent"):
        cmd = _agent_command(repo_root, overlay, step, args)
        log(f"AGENT {label}: claude {'-p ' if not args.interactive else ''}<{step['agent']}>")
        proc = subprocess.run(
            cmd,
            cwd=str(repo_root),
            env=_step_env(overlay),
            capture_output=not args.interactive,
            text=True,
        )
        if not args.interactive:
            try:
                payload = json.loads(proc.stdout or "{}")
                log(f"      {payload.get('result', proc.stdout).strip()[:2000]}")
            except json.JSONDecodeError:
                log(f"      {(proc.stdout or proc.stderr).strip()[:2000]}")
        if proc.returncode != 0:
            return "failed"
    else:
        log(f"MANUAL {label}: {step.get('manual', 'no instructions supplied')}")
        return "manual"

    return "ok" if _run_check(repo_root, overlay, step) is not False else "unverified"


def _remote_host(target: Path) -> str | None:
    probe = target if target.is_dir() else target.parent
    if not probe.is_dir():
        return None  # a project since deleted, or one on another machine
    try:
        root = _git(["rev-parse", "--show-toplevel"], cwd=probe)
        url = _git(["remote", "get-url", "origin"], cwd=Path(root))
    except OverlayError:
        return None
    match = re.search(r"(?:://|@)([^/:]+)", url)
    return match.group(1) if match else None


def _claims(overlay: Overlay, target: Path, host: str | None) -> bool:
    claims = overlay.manifest().get("claims") or {}
    if host and any(fnmatch(host, pattern) for pattern in claims.get("remotes", [])):
        return True
    for pattern in claims.get("paths", []):
        expanded = str(Path(pattern).expanduser())
        if fnmatch(str(target), expanded) or str(target).startswith(expanded.rstrip("/") + "/"):
            return True
    return False


def route(
    repo_root: Path, target: Path, host: str | None = None, default: bool = True
) -> Overlay | None:
    """The overlay that owns `target`: one whose claims match, else the default one.

    Higher priority wins among several. Other tools route their records with
    this too (the worklog journal picks its repo here), so the rule lives in
    one place. With default=False an unclaimed target gives None, for a caller
    whose own fallback differs from the claims default.
    """
    if host is None:
        host = _remote_host(target)
    candidates = enabled_overlays(repo_root)
    matched = [o for o in candidates if _claims(o, target, host)]
    if not matched:
        if not default:
            return None
        matched = [o for o in candidates if (o.manifest().get("claims") or {}).get("default")]
    winner = max(matched, key=lambda o: (o.priority, o.alias), default=None)
    if winner is None:
        raise OverlayError(f"no overlay claims {target}, and none is marked default")
    return winner


def cmd_route(repo_root: Path, args, log) -> int:
    """Which overlay owns a piece of work — so records land in the right repo."""
    target = Path(args.path).expanduser().resolve() if args.path else Path.cwd()
    host = _remote_host(target)
    winner = route(repo_root, target, host)
    if args.explain:
        log(f"{target} (remote host: {host or 'none'}) -> {winner.alias}")
    elif args.dir:
        destination = winner.path / args.dir
        if args.mkdir:
            destination.mkdir(parents=True, exist_ok=True)
        log(str(destination))
    else:
        log(winner.alias)
    return 0


def cmd_setup(repo_root: Path, args, log) -> int:
    overlays = layers(repo_root)  # the base first, so its steps run before the overlays'
    if args.alias:
        overlays = [o for o in overlays if o.alias == args.alias]
        if not overlays:
            raise OverlayError(f"no base or enabled overlay registered as '{args.alias}'")

    plan: list[tuple[object, dict, bool | None]] = []
    for overlay in overlays:
        for step in overlay.manifest().get("setup", []):
            if args.only and step.get("id") not in args.only:
                continue
            plan.append((overlay, step, _run_check(repo_root, overlay, step)))

    if not plan:
        log("setup: no steps declared")
        return 0

    log(f"{'STEP':<28} {'STATE':<9} HOW")
    for overlay, step, state in plan:
        how = "run" if step.get("run") else "agent" if step.get("agent") else "manual"
        label = "ok" if state else "pending" if state is False else "unknown"
        log(f"{overlay.alias + '/' + step['id']:<28} {label:<9} {how}: {step.get('description', '')}")

    pending = [(o, s) for o, s, state in plan if state is not True]
    if not pending:
        log("setup: everything already satisfied")
        return 0
    if args.dry_run:
        log(f"setup: {len(pending)} step(s) would run (dry run)")
        return 0
    if not args.yes:
        raise OverlayError(
            f"{len(pending)} step(s) pending. These run commands and agents from the overlay — "
            "review them, then re-run with --yes"
        )

    results = {}
    for overlay, step in pending:
        results[f"{overlay.alias}/{step['id']}"] = _run_step(repo_root, overlay, step, args, log)

    log("")
    for label, outcome in results.items():
        log(f"{outcome.upper():<11} {label}")
    return 0 if all(v == "ok" for v in results.values()) else 1


def cmd_update(repo_root: Path, args, log) -> int:
    overlays = load_registry(repo_root)
    if args.alias:
        overlays = [o for o in overlays if o.alias == args.alias]
        if not overlays:
            raise OverlayError(f"no overlay registered as '{args.alias}'")

    applied = load_applied(repo_root)
    for overlay in overlays:
        if not overlay.cloned:
            log(f"SKIP  {overlay.alias} (not cloned)")
            continue
        if not overlay.url:
            log(f"SKIP  {overlay.alias} (no remote — nothing to pull)")
        else:
            if overlay.apply_mode != APPLY_CHECKOUT and _upstream_in_checkout_layout(overlay):
                # Pulling it into a symlink-mode clone would move every file
                # under overlays/<alias>/overlays/<alias>/ and drop the overlay.
                log(f"STOP  {overlay.alias}: upstream moved to the checkout layout — run 'overlay.py convert {overlay.alias}'")
                continue
            log(f"RUN   git -C {overlay.path} pull --ff-only")
            _git(["pull", "--ff-only"], cwd=overlay.path)
        if overlay.enabled:
            applied = apply_overlay(repo_root, overlay, applied, log)

    save_applied(repo_root, applied)
    sync_git_exclude(repo_root, applied)
    sync_ignore_file(repo_root, applied)
    _render(repo_root)
    return 0


def _upstream_in_checkout_layout(overlay: Overlay) -> bool:
    _git(["fetch", "-q", "origin", overlay.ref], cwd=overlay.path)
    return _tree_has(overlay, "FETCH_HEAD", f"{OVERLAYS_REL}/{overlay.alias}/{MANIFEST_NAME}")


def _remove_checkout_files(repo_root: Path, overlay: Overlay, purge: bool, log) -> None:
    """Delete a checkout overlay's view files, but only when nothing in them can be lost."""
    if not purge:
        raise OverlayError(
            f"{overlay.alias} keeps its view files in place (checkout mode), so removing it deletes them — "
            "rerun with --purge once its work is committed and pushed"
        )
    if _git(["status", "--porcelain"], cwd=overlay.path):
        raise OverlayError(f"{overlay.alias} has uncommitted changes; commit or discard them first")
    try:
        ahead = _git(["rev-list", "--count", "@{u}..HEAD"], cwd=overlay.path)
    except OverlayError:
        raise OverlayError(f"{overlay.alias} has no upstream to compare with; push it first, or remove it by hand") from None
    if ahead != "0":
        raise OverlayError(f"{overlay.alias} has {ahead} unpushed commit(s); push them first")

    removed = 0
    for rel in _overlay_tracked(overlay):
        path = repo_root / rel
        if _view_unit(rel) and path.is_file() and not path.is_symlink():
            path.unlink()
            removed += 1
    for unit in owned_view_units(overlay):
        top = repo_root / unit
        if top.is_dir() and not top.is_symlink():
            for dirpath, _dirnames, _filenames in os.walk(top, topdown=False):
                if not os.listdir(dirpath):
                    os.rmdir(dirpath)
            if top.exists():
                log(f"KEEP  {unit} (holds files the overlay does not track)")
    log(f"REMOVE {removed} view file(s) of '{overlay.alias}'")


def cmd_convert(repo_root: Path, args, log) -> int:
    """Turn a symlink-mode clone into a checkout-mode one, in place.

    The target commit must be a pure restructure: every path moved, either to
    overlays/<alias>/<same path> or into its view dir, and no content changed.
    Then git's index can be switched to it without touching a file, the view
    files are renamed over their symlinks, and nothing the base has is ever
    written: checkout-index only fills in files that are missing.
    """
    overlay = next((o for o in load_registry(repo_root) if o.alias == args.alias), None)
    if overlay is None or not overlay.cloned:
        raise OverlayError(f"no cloned overlay registered as '{args.alias}'")
    if is_checkout_clone(overlay):
        log(f"{overlay.alias} is already checked out in place")
        return 0
    path, alias = overlay.path, overlay.alias
    source, ref = args.source or "origin", args.ref or overlay.ref

    log(f"RUN   git -C {path} fetch {source} {ref}")
    _git(["fetch", "-q", source, ref], cwd=path)
    target = _git(["rev-parse", "FETCH_HEAD"], cwd=path)
    nested = f"{OVERLAYS_REL}/{alias}/{MANIFEST_NAME}"
    if not _tree_has(overlay, target, nested):
        raise OverlayError(f"{alias}: {source} {ref} is not in the checkout layout (no {nested})")

    parent = _git(["rev-parse", f"{target}^"], cwd=path)
    head = _git(["rev-parse", "HEAD"], cwd=path)
    if head != parent:
        try:
            _git(["merge-base", "--is-ancestor", head, parent], cwd=path)
        except OverlayError:
            raise OverlayError(f"{alias}: HEAD has commits that {ref} does not; put them under the restructure first") from None
        if args.dry_run:
            log(f"WOULD fast-forward {alias} to {parent[:12]} in the old layout first")
        else:
            if _git(["status", "--porcelain", "--untracked-files=no"], cwd=path):
                raise OverlayError(f"{alias}: commit its changes first, so the fast-forward cannot conflict")
            log(f"RUN   git -C {path} merge --ff-only {parent[:12]}")
            _git(["merge", "--ff-only", "-q", parent], cwd=path)

    lines = [line for line in _git(["diff", "--name-status", "-M100%", parent, target], cwd=path).splitlines() if line]
    changed = [line for line in lines if not line.startswith("R100\t")]
    if changed:
        raise OverlayError(f"{alias}: {target[:12]} must only move files, but it also changes: {', '.join(changed[:5])}")
    own = f"{OVERLAYS_REL}/{alias}/"
    for _status, old, new in (line.split("\t") for line in lines):
        if new != own + old and _view_overlay_rel(new) != old:
            raise OverlayError(f"{alias}: {old} -> {new} is neither overlays/{alias}/{old} nor its view path")

    units = owned_view_units(overlay, target)
    # Symlink mode links every file in the namespaces, tracked or not; the
    # target commit carries only tracked ones. A file linked now but missing
    # from the target would silently drop out of view.
    linked_now = {
        str(view.relative_to(repo_root))
        for _source, view in _planned_links(overlay)
        if _view_unit(str(view.relative_to(repo_root)))
    }
    stray = sorted(linked_now - set(units))
    if stray:
        raise OverlayError(
            f"{alias}: in view now but not tracked by {target[:12]}, so they would drop out: {', '.join(stray)} — "
            "commit them in the overlay and make the restructure commit on top, or move them out first"
        )
    applied = load_applied(repo_root)
    others = {item["link"]: item["alias"] for item in applied if item["alias"] != alias}
    conflicts = [f"{unit} (overlay '{others[unit]}' already provides it)" for unit in units if unit in others]
    conflicts += [f"{unit} (base repo already has it)" for unit in sorted(_base_tracked(repo_root, units))]
    moves: list[tuple[Path, Path]] = []
    for unit in units:
        old, new = path / _view_overlay_rel(unit), repo_root / unit
        if new.is_symlink():
            if os.path.realpath(new) != os.path.realpath(old):
                conflicts.append(f"{unit} (a symlink to somewhere else)")
        elif new.exists():
            conflicts.append(f"{unit} (something is already there)")
        moves.append((old, new))
    if conflicts:
        raise OverlayError(f"{alias}: refusing to convert —\n  " + "\n  ".join(conflicts))

    if args.dry_run:
        for old, new in moves:
            note = "" if old.exists() else " (missing here; checked out from git)"
            log(f"MOVE  {old.relative_to(repo_root)} -> {new.relative_to(repo_root)}{note}")
        log(f"dry run: {len(moves)} view unit(s) would move into place; nothing was changed")
        return 0

    gitdir = Path(_git(["rev-parse", "--path-format=absolute", "--git-dir"], cwd=path))
    backup = gitdir / f"agents-convert-{time.strftime('%Y%m%d-%H%M%S')}"
    backup.mkdir()
    shutil.copy2(gitdir / "config", backup / "config")
    if (gitdir / "index").is_file():
        shutil.copy2(gitdir / "index", backup / "index")
    (backup / "ORIG_HEAD").write_text(head + "\n")
    log(f"SAVE  {backup} (config, index and HEAD from before the switch)")

    # Switch what git sees, without touching a file.
    _git(["config", "core.worktree", CHECKOUT_WORKTREE], cwd=path)
    _git(["config", "status.showUntrackedFiles", "no"], cwd=path)
    _git(["read-tree", "--empty"], cwd=path)
    _git(["reset", "--soft", target], cwd=path)
    _git(["read-tree", target], cwd=path)

    for old, new in moves:
        if not old.exists():
            continue
        new.parent.mkdir(parents=True, exist_ok=True)
        if old.is_dir():
            aside = new.with_name(new.name + ".convert-link") if new.is_symlink() else None
            if aside:
                os.rename(new, aside)
            os.rename(old, new)
            if aside:
                aside.unlink()
        else:
            os.replace(old, new)  # atomic: the symlink is replaced by the file it pointed at
        log(f"MOVE  {old.relative_to(repo_root)} -> {new.relative_to(repo_root)}")

    missing = [rel for rel in _overlay_tracked(overlay) if _view_unit(rel) and not (repo_root / rel).exists()]
    if missing:
        _git_at_root(overlay, ["checkout-index", "-q", "--", *missing])
        log(f"CHECKOUT {len(missing)} missing view file(s) from git")
    try:
        _git(["update-index", "-q", "--refresh"], cwd=path)
    except OverlayError:
        pass  # files with local edits; status below shows them

    applied = apply_overlay(repo_root, overlay, applied, log)
    save_applied(repo_root, applied)
    sync_git_exclude(repo_root, applied)
    sync_ignore_file(repo_root, applied)
    _render(repo_root)
    for line in _git(["status", "--porcelain"], cwd=path).splitlines():
        log(f"STATUS {line}")
    log(f"converted '{alias}' to checkout mode; to undo, see {backup} and docs/overlay.md")
    return 0


def cmd_sync_views(repo_root: Path, args, log) -> int:
    """Refresh checkout overlays' records, the exclude list and .ignore. The overlays' hooks run this."""
    applied = load_applied(repo_root)
    for overlay in enabled_overlays(repo_root):
        if overlay.apply_mode != APPLY_CHECKOUT or not is_checkout_clone(overlay):
            continue
        rest = [item for item in applied if not (item["alias"] == overlay.alias and item.get("mode") == APPLY_CHECKOUT)]
        others = {item["link"]: item["alias"] for item in rest if item["alias"] != overlay.alias}
        applied = rest + _checkout_items(repo_root, overlay, others)
    save_applied(repo_root, applied)
    sync_git_exclude(repo_root, applied)
    sync_ignore_file(repo_root, applied)
    return 0


def cmd_remove(repo_root: Path, args, log) -> int:
    overlays = load_registry(repo_root)
    target = next((o for o in overlays if o.alias == args.alias), None)
    if target is None:
        raise OverlayError(f"no overlay registered as '{args.alias}'")
    if target.cloned and is_checkout_clone(target):
        _remove_checkout_files(repo_root, target, args.purge, log)

    applied = unapply_overlay(repo_root, args.alias, load_applied(repo_root), log)
    # A path this overlay had taken from a lower-priority one falls back to it,
    # rather than disappearing until someone runs install again.
    for entry in enabled_overlays(repo_root):
        if entry.alias != args.alias:
            applied = apply_overlay(repo_root, entry, applied, log)
    save_applied(repo_root, applied)
    sync_git_exclude(repo_root, applied)
    sync_ignore_file(repo_root, applied)
    save_registry(repo_root, [o for o in overlays if o.alias != args.alias])

    if args.purge and target.path.exists():
        shutil.rmtree(target.path)
        log(f"PURGE {target.path}")

    _render(repo_root)
    log(f"removed '{args.alias}'")
    return 0


def cmd_init(repo_root: Path, args, log) -> int:
    template = repo_root / TEMPLATE_REL
    if not template.is_dir():
        raise OverlayError(f"template missing: {TEMPLATE_REL}")

    # A bare alias scaffolds in place under overlays/; a path goes where it says.
    raw = args.dest
    dest = repo_root / OVERLAYS_REL / raw if "/" not in raw else Path(raw).expanduser()
    dest = dest.resolve()
    if dest.exists():
        raise OverlayError(f"{dest} already exists")
    if dest.parent == (repo_root / OVERLAYS_REL).resolve():
        private_overlays_dir(repo_root)

    shutil.copytree(template, dest)
    name = args.name or dest.name
    manifest_path = dest / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text())
    manifest["name"] = name
    manifest_path.write_text(dumps(manifest))

    log(f"scaffolded overlay '{name}' at {dest}")
    log(f"next: cd {dest} && git init -b main && git add -A && git commit")
    log("      add a private remote and push, then back in the harness repo:")
    log(f"      scripts/overlay.py add {name} && scripts/overlay.py install {name}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Manage environment overlays.")
    p.add_argument("--repo", type=Path, default=None, help="override repo root")
    sub = p.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="register an overlay repo, cloning it if absent")
    add.add_argument("alias")
    add.add_argument("url", nargs="?", help="omit when overlays/<alias> is already a clone")
    add.add_argument("--ref", default="main")
    add.add_argument("--priority", type=int, default=None)
    add.set_defaults(func=cmd_add)

    install = sub.add_parser("install", help="apply overlays and re-render settings")
    install.add_argument("alias", nargs="?")
    install.add_argument(
        "--dry-run",
        action="store_true",
        help="show the links and rendered settings that would change, and change nothing",
    )
    install.set_defaults(func=cmd_install)

    listing = sub.add_parser("list", help="show registered overlays")
    listing.set_defaults(func=cmd_list)

    status = sub.add_parser("status", help="report link drift and render drift")
    status.set_defaults(func=cmd_status)

    route = sub.add_parser("route", help="say which overlay owns a path, so records land in the right repo")
    route.add_argument("path", nargs="?", help="defaults to the current directory")
    route.add_argument("--dir", default=None, help="print <overlay>/<dir> instead of the alias")
    route.add_argument("--mkdir", action="store_true", help="create that directory if missing")
    route.add_argument("--explain", action="store_true", help="show the path, its remote host and the winner")
    route.set_defaults(func=cmd_route)

    setup = sub.add_parser("setup", help="run the environment setup steps an overlay declares")
    setup.add_argument("alias", nargs="?")
    setup.add_argument("--only", nargs="*", default=None, help="limit to these step ids")
    setup.add_argument("--dry-run", action="store_true", help="show the plan and stop")
    setup.add_argument("--yes", action="store_true", help="run the pending steps")
    setup.add_argument(
        "--interactive",
        action="store_true",
        help="hand agent steps to a live claude session instead of claude -p",
    )
    setup.add_argument(
        "--permission-mode",
        default="acceptEdits",
        choices=["acceptEdits", "auto", "plan", "dontAsk", "manual", "bypassPermissions"],
    )
    setup.add_argument("--model", default=None, help="model for agent steps")
    setup.set_defaults(func=cmd_setup)

    update = sub.add_parser("update", help="pull overlay repos and re-apply")
    update.add_argument("alias", nargs="?")
    update.set_defaults(func=cmd_update)

    convert = sub.add_parser("convert", help="switch a symlink-mode clone to checkout mode, in place")
    convert.add_argument("alias")
    convert.add_argument("--source", default=None, help="remote or path to fetch the restructured commit from (default origin)")
    convert.add_argument("--ref", default=None, help="branch to fetch (default the registered ref)")
    convert.add_argument("--dry-run", action="store_true", help="show the moves and stop")
    convert.set_defaults(func=cmd_convert)

    sync_views = sub.add_parser("sync-views", help="refresh checkout overlays' records, exclude list and .ignore")
    sync_views.set_defaults(func=cmd_sync_views)

    file_ = sub.add_parser("file", help="give an unfiled view file its owner: stage it in the base or an overlay")
    file_.add_argument("path", help="the file, or skill directory, in a view dir (shared/memory/x.md, universal/skills/x)")
    file_.add_argument("--to", required=True, help="'base' or an overlay alias")
    file_.set_defaults(func=cmd_file)

    check = sub.add_parser("check-staged", help="the base repo's pre-commit guard (run by the hook)")
    check.set_defaults(func=cmd_check_staged)

    remove = sub.add_parser("remove", help="unlink an overlay and forget it")
    remove.add_argument("alias")
    remove.add_argument("--purge", action="store_true", help="also delete the clone")
    remove.set_defaults(func=cmd_remove)

    init = sub.add_parser("init", help="scaffold a new overlay repo from the template")
    init.add_argument("dest", help="an alias (scaffolds overlays/<alias>) or an explicit path")
    init.add_argument("--name", default=None)
    init.set_defaults(func=cmd_init)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = (args.repo or Path(__file__).resolve().parent.parent).resolve()
    try:
        return args.func(repo_root, args, lambda msg: print(msg))
    except OverlayError as exc:
        print(f"overlay: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
