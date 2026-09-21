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
from dataclasses import dataclass, field
from pathlib import Path

from install import Mkdir, Symlink
from render_settings import dumps, render_all

OVERLAYS_REL = "overlays"
REGISTRY_REL = "overlays/registry.local.json"
APPLIED_REL = "overlays/applied.local.json"
TEMPLATE_REL = "templates/overlay-example"
MANIFEST_NAME = "overlay.json"
VARS_NAME = "vars.json"

EXCLUDE_BEGIN = "# >>> agents-overlay >>>"
EXCLUDE_END = "# <<< agents-overlay <<<"

# (overlay dir, base dir, glob or None for directory drop-ins)
LINK_MAP = (
    ("memory", "shared/memory", "*.md"),
    ("instructions", "shared/instructions", "*.md"),
    ("commands", "shared/commands", "*.md"),
    ("subagents", "shared/subagents", "*.md"),
    ("skills", "universal/skills", None),
)

ALIAS_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


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

    @property
    def path(self) -> Path:
        return self.repo_root / OVERLAYS_REL / self.alias

    @property
    def cloned(self) -> bool:
        return (self.path / MANIFEST_NAME).is_file()

    def manifest(self) -> dict:
        target = self.path / MANIFEST_NAME
        return json.loads(target.read_text()) if target.is_file() else {}

    def variables(self) -> dict:
        target = self.path / VARS_NAME
        return json.loads(target.read_text()) if target.is_file() else {}

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


def save_registry(repo_root: Path, overlays: list[Overlay]) -> None:
    path = repo_root / REGISTRY_REL
    path.parent.mkdir(parents=True, exist_ok=True)
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
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(links, key=lambda item: (item["alias"], item["link"]))
    path.write_text(dumps({"links": ordered}))


def sync_git_exclude(repo_root: Path, links: list[dict]) -> None:
    """Keep overlay-provided symlinks out of `git status` without touching .gitignore."""
    try:
        exclude = Path(_git(["rev-parse", "--git-path", "info/exclude"], cwd=repo_root))
    except OverlayError:
        return
    if not exclude.is_absolute():
        exclude = repo_root / exclude
    exclude.parent.mkdir(parents=True, exist_ok=True)
    current = exclude.read_text().splitlines() if exclude.is_file() else []

    kept: list[str] = []
    skipping = False
    for line in current:
        if line.strip() == EXCLUDE_BEGIN:
            skipping = True
            continue
        if line.strip() == EXCLUDE_END:
            skipping = False
            continue
        if not skipping:
            kept.append(line)

    while kept and not kept[-1].strip():
        kept.pop()

    block = [EXCLUDE_BEGIN] + sorted({f"/{item['link']}" for item in links}) + [EXCLUDE_END]
    body = kept + ([""] if kept else []) + (block if links else [])
    exclude.write_text("\n".join(body).rstrip("\n") + "\n")


# ---------------------------------------------------------------------------
# Apply / unapply
# ---------------------------------------------------------------------------


def _planned_links(overlay: Overlay) -> list[tuple[Path, Path]]:
    """(source, target) pairs this overlay contributes, both absolute."""
    pairs: list[tuple[Path, Path]] = []
    for src_rel, dst_rel, pattern in LINK_MAP:
        src_dir = overlay.path / src_rel
        if not src_dir.is_dir():
            continue
        dst_dir = overlay.repo_root / dst_rel
        items = sorted(src_dir.glob(pattern)) if pattern else sorted(p for p in src_dir.iterdir() if p.is_dir())
        for item in items:
            pairs.append((item, dst_dir / item.name))

    # Escape hatch for anything the fixed namespaces don't cover.
    for src_rel, dst_rel in overlay.manifest().get("links", {}).items():
        source = overlay.path / src_rel
        if not source.exists():
            raise OverlayError(f"{overlay.alias}: links entry '{src_rel}' does not exist in the overlay")
        pairs.append((source, overlay.repo_root / dst_rel))
    return pairs


def _relative_symlink(source: Path, target: Path) -> Path:
    return Path(os.path.relpath(source, target.parent))


def apply_overlay(repo_root: Path, overlay: Overlay, applied: list[dict], log) -> list[dict]:
    if not overlay.cloned:
        raise OverlayError(f"{overlay.alias}: not cloned — run 'overlay.py add' first")

    mine = {item["link"] for item in applied if item["alias"] == overlay.alias}
    others = {item["link"]: item["alias"] for item in applied if item["alias"] != overlay.alias}

    planned = _planned_links(overlay)
    conflicts = []
    for source, target in planned:
        rel = str(target.relative_to(repo_root))
        if rel in others:
            conflicts.append(f"{rel} (already provided by '{others[rel]}')")
        elif (target.exists() or target.is_symlink()) and rel not in mine:
            if not (target.is_symlink() and target.resolve() == source.resolve()):
                conflicts.append(f"{rel} (base repo already has it)")
    if conflicts:
        raise OverlayError(f"{overlay.alias}: refusing to apply —\n  " + "\n  ".join(conflicts))

    ops = []
    links = [item for item in applied if item["alias"] != overlay.alias]
    for source, target in planned:
        rel_source = _relative_symlink(source, target)
        if target.is_symlink():
            target.unlink()
        Mkdir(target.parent).apply()
        op = Symlink(rel_source, target)
        op.apply()
        ops.append(op)
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
        _unlink(repo_root / stale, log)

    return links


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
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise OverlayError(f"git {' '.join(args)} failed:\n{proc.stderr.strip()}")
    return proc.stdout.strip()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_add(repo_root: Path, args, log) -> int:
    if not ALIAS_RE.match(args.alias):
        raise OverlayError(f"invalid alias '{args.alias}' (use lowercase letters, digits, - and _)")

    overlays = load_registry(repo_root)
    if any(o.alias == args.alias for o in overlays):
        raise OverlayError(f"alias '{args.alias}' is already registered")

    entry = Overlay(
        alias=args.alias,
        url=args.url,
        ref=args.ref,
        priority=args.priority,
        repo_root=repo_root,
    )
    if entry.path.exists():
        raise OverlayError(f"{entry.path} already exists")

    entry.path.parent.mkdir(parents=True, exist_ok=True)
    clone = ["clone", "--branch", args.ref, args.url, str(entry.path)]
    log(f"RUN   git {' '.join(clone)}")
    _git(clone)

    if not entry.cloned:
        shutil.rmtree(entry.path, ignore_errors=True)
        raise OverlayError(f"{args.url} has no {MANIFEST_NAME} — not an overlay repo")

    overlays.append(entry)
    save_registry(repo_root, overlays)
    log(f"added '{args.alias}' (priority {args.priority}). Run 'overlay.py install {args.alias}' to apply.")
    return 0


def cmd_install(repo_root: Path, args, log) -> int:
    overlays = load_registry(repo_root)
    if args.alias:
        overlays = [o for o in overlays if o.alias == args.alias]
        if not overlays:
            raise OverlayError(f"no overlay registered as '{args.alias}'")
    else:
        overlays = [o for o in overlays if o.enabled]

    applied = load_applied(repo_root)
    for overlay in overlays:
        applied = apply_overlay(repo_root, overlay, applied, log)

    save_applied(repo_root, applied)
    sync_git_exclude(repo_root, applied)
    for rel, merged in render_all(repo_root).items():
        if merged:
            log(f"RENDER {rel} (base + {len(enabled_overlays(repo_root))} overlay(s))")
    return 0


def cmd_list(repo_root: Path, args, log) -> int:
    overlays = load_registry(repo_root)
    if not overlays:
        log("no overlays registered")
        return 0

    applied = load_applied(repo_root)
    counts: dict[str, int] = {}
    for item in applied:
        counts[item["alias"]] = counts.get(item["alias"], 0) + 1

    log(f"{'ALIAS':<16} {'PRIO':>4}  {'STATE':<12} {'LINKS':>5}  REF     URL")
    for overlay in overlays:
        if not overlay.cloned:
            state = "not-cloned"
        elif not overlay.enabled:
            state = "disabled"
        elif overlay.alias in counts:
            state = "applied"
        else:
            state = "registered"
        log(
            f"{overlay.alias:<16} {overlay.priority:>4}  {state:<12} "
            f"{counts.get(overlay.alias, 0):>5}  {overlay.ref:<7} {overlay.url}"
        )
    return 0


def cmd_status(repo_root: Path, args, log) -> int:
    problems = 0
    applied = load_applied(repo_root)

    for item in applied:
        link = repo_root / item["link"]
        source = repo_root / item["source"]
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

    if (repo_root / "claude" / "settings.base.json").is_file():
        for rel, merged in render_all(repo_root, write=False).items():
            if not merged:
                continue
            artifact = repo_root / rel
            if not artifact.is_file() or artifact.read_text() != dumps(merged):
                log(f"DRIFT {rel} differs from a fresh render — run 'overlay.py install'")
                problems += 1

    if problems == 0:
        log(f"overlay: clean ({len(applied)} link(s))")
    return 1 if problems else 0


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
        log(f"RUN   git -C {overlay.path} pull --ff-only")
        _git(["pull", "--ff-only"], cwd=overlay.path)
        if overlay.enabled:
            applied = apply_overlay(repo_root, overlay, applied, log)

    save_applied(repo_root, applied)
    sync_git_exclude(repo_root, applied)
    render_all(repo_root)
    return 0


def cmd_remove(repo_root: Path, args, log) -> int:
    overlays = load_registry(repo_root)
    target = next((o for o in overlays if o.alias == args.alias), None)
    if target is None:
        raise OverlayError(f"no overlay registered as '{args.alias}'")

    applied = unapply_overlay(repo_root, args.alias, load_applied(repo_root), log)
    save_applied(repo_root, applied)
    sync_git_exclude(repo_root, applied)
    save_registry(repo_root, [o for o in overlays if o.alias != args.alias])

    if args.purge and target.path.exists():
        shutil.rmtree(target.path)
        log(f"PURGE {target.path}")

    render_all(repo_root)
    log(f"removed '{args.alias}'")
    return 0


def cmd_init(repo_root: Path, args, log) -> int:
    template = repo_root / TEMPLATE_REL
    if not template.is_dir():
        raise OverlayError(f"template missing: {TEMPLATE_REL}")

    dest = Path(args.dest).expanduser().resolve()
    if dest.exists():
        raise OverlayError(f"{dest} already exists")

    shutil.copytree(template, dest)
    name = args.name or dest.name
    manifest_path = dest / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text())
    manifest["name"] = name
    manifest_path.write_text(dumps(manifest))

    log(f"scaffolded overlay '{name}' at {dest}")
    log("next: git init && git add -A && git commit, push to a private remote,")
    log(f"      then: scripts/overlay.py add {name} <git-url>")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Manage environment overlays.")
    p.add_argument("--repo", type=Path, default=None, help="override repo root")
    sub = p.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="register and clone an overlay repo")
    add.add_argument("alias")
    add.add_argument("url")
    add.add_argument("--ref", default="main")
    add.add_argument("--priority", type=int, default=50)
    add.set_defaults(func=cmd_add)

    install = sub.add_parser("install", help="apply overlays and re-render settings")
    install.add_argument("alias", nargs="?")
    install.set_defaults(func=cmd_install)

    listing = sub.add_parser("list", help="show registered overlays")
    listing.set_defaults(func=cmd_list)

    status = sub.add_parser("status", help="report link drift and render drift")
    status.set_defaults(func=cmd_status)

    update = sub.add_parser("update", help="pull overlay repos and re-apply")
    update.add_argument("alias", nargs="?")
    update.set_defaults(func=cmd_update)

    remove = sub.add_parser("remove", help="unlink an overlay and forget it")
    remove.add_argument("alias")
    remove.add_argument("--purge", action="store_true", help="also delete the clone")
    remove.set_defaults(func=cmd_remove)

    init = sub.add_parser("init", help="scaffold a new overlay repo from the template")
    init.add_argument("dest")
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
