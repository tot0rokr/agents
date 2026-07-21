#!/usr/bin/env python3
"""Install per-tool symlinks from this repo into the user's home directory.

After running, each CLI agent reads its config from this repo:

    ~/.claude            -> agents/claude
    ~/.codex             -> agents/codex
    ~/.config/opencode   -> agents/opencode
    ~/.gemini            -> agents/gemini
    ~/.agents            -> agents/universal   (codex/opencode/gemini fallback)

Three phases run in order:

    Phase 1  top-level home symlinks (existing real dirs backed up to .bak)
    Phase 2  Claude per-project memory unification into shared/memory
    Phase 3  runtime data restore from the fresh ~/.claude backup

Every mutating operation is recorded; if any phase raises, the recorded
operations are undone in reverse and the script exits non-zero.

This module is intended to be both a CLI (`python3 install.py`) and a
library (`from install import install; install(home=..., repo_root=...)`)
so the harness-adapter-mcp server can call it in-process.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

LINK_PATHS = [
    (".claude", "claude"),
    (".codex", "codex"),
    (".config/opencode", "opencode"),
    (".gemini", "gemini"),
    (".agents", "universal"),
]

# Codex/OpenCode/Gemini settle their own paths; only Claude has the
# per-project memory channel that we want to unify.
MEMORY_PARENT = ".claude/projects"
SHARED_MEMORY_REL = "shared/memory"


# ---------------------------------------------------------------------------
# Operation primitives — each captures enough state to undo itself.
# ---------------------------------------------------------------------------


class Op:
    """Base mutation. Subclasses implement apply/rollback."""

    description: str = "noop"

    def apply(self) -> None:
        raise NotImplementedError

    def rollback(self) -> None:
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"<{type(self).__name__}: {self.description}>"


@dataclass
class Mkdir(Op):
    path: Path
    _created: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        self.description = f"mkdir -p {self.path}"

    def apply(self) -> None:
        if self.path.exists():
            return
        self.path.mkdir(parents=True)
        self._created = True

    def rollback(self) -> None:
        if not self._created:
            return
        # Only remove if still empty — never delete dirs the user put things in.
        try:
            self.path.rmdir()
        except OSError:
            pass


@dataclass
class Symlink(Op):
    source: Path
    target: Path

    def __post_init__(self) -> None:
        self.description = f"ln -s {self.source} {self.target}"

    def apply(self) -> None:
        if self.target.is_symlink() and Path(os.readlink(self.target)) == self.source:
            return
        self.target.symlink_to(self.source)

    def rollback(self) -> None:
        if not self.target.is_symlink():
            return
        if Path(os.readlink(self.target)) != self.source:
            return
        self.target.unlink()


@dataclass
class Backup(Op):
    """`mv src -> dst`. Used to move existing real dirs out of the way."""

    src: Path
    dst: Path

    def __post_init__(self) -> None:
        self.description = f"mv {self.src} -> {self.dst}"

    def apply(self) -> None:
        shutil.move(str(self.src), str(self.dst))

    def rollback(self) -> None:
        if self.src.exists() or self.src.is_symlink():
            # During Phase 1 a symlink may have been put in place after the
            # backup; remove it before restoring the original directory.
            if self.src.is_symlink():
                self.src.unlink()
            else:
                # Real dir exists at the original path — refuse to clobber.
                return
        shutil.move(str(self.dst), str(self.src))


@dataclass
class CopyFile(Op):
    src: Path
    dst: Path
    _dst_existed: bool = field(default=False, init=False)
    _dst_backup: Path | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self.description = f"cp {self.src} -> {self.dst}"

    def apply(self) -> None:
        if self.dst.exists():
            self._dst_existed = True
            self._dst_backup = self.dst.with_suffix(self.dst.suffix + ".preinstall-tmp")
            shutil.copy2(self.dst, self._dst_backup)
        shutil.copy2(self.src, self.dst)

    def rollback(self) -> None:
        if not self.dst.exists():
            return
        if self._dst_existed and self._dst_backup and self._dst_backup.exists():
            shutil.move(str(self._dst_backup), str(self.dst))
        else:
            self.dst.unlink()


@dataclass
class CopyTree(Op):
    src: Path
    dst: Path

    def __post_init__(self) -> None:
        self.description = f"cp -r {self.src} -> {self.dst}"

    def apply(self) -> None:
        if self.dst.exists():
            raise RuntimeError(f"refusing to overwrite existing tree {self.dst}")
        shutil.copytree(self.src, self.dst, symlinks=True)

    def rollback(self) -> None:
        if self.dst.exists():
            shutil.rmtree(self.dst)


@dataclass
class MergeMissingFiles(Op):
    """Copy files from src that don't exist in dst. Records what we added."""

    src: Path
    dst: Path
    _added: list[Path] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        self.description = f"merge-missing {self.src}/* -> {self.dst}/"

    def apply(self) -> None:
        if not self.src.is_dir():
            return
        self.dst.mkdir(parents=True, exist_ok=True)
        for child in self.src.iterdir():
            target = self.dst / child.name
            if target.exists():
                continue
            if child.is_dir():
                shutil.copytree(child, target, symlinks=True)
            else:
                shutil.copy2(child, target)
            self._added.append(target)

    def rollback(self) -> None:
        for path in self._added:
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path, ignore_errors=True)
            elif path.exists() or path.is_symlink():
                path.unlink()


@dataclass
class ConcatFile(Op):
    """Prepend `prefix_src` content onto `target` (target may not exist)."""

    prefix_src: Path
    target: Path
    _target_existed: bool = field(default=False, init=False)
    _target_backup: Path | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self.description = f"concat {self.prefix_src} + {self.target}"

    def apply(self) -> None:
        if self.target.exists():
            self._target_existed = True
            self._target_backup = self.target.with_suffix(
                self.target.suffix + ".preinstall-tmp"
            )
            shutil.copy2(self.target, self._target_backup)
            existing = self.target.read_bytes()
        else:
            existing = b""
        prefix = self.prefix_src.read_bytes()
        self.target.write_bytes(prefix + existing)

    def rollback(self) -> None:
        if not self.target.exists():
            return
        if self._target_existed and self._target_backup and self._target_backup.exists():
            shutil.move(str(self._target_backup), str(self.target))
        else:
            self.target.unlink()


@dataclass
class MergeJsonPermissions(Op):
    """Merge `bak_src.permissions.allow` into `target.permissions.allow`."""

    bak_src: Path
    target: Path
    _target_backup: Path | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self.description = f"merge-permissions {self.bak_src} -> {self.target}"

    def apply(self) -> None:
        if not self.target.exists():
            shutil.copy2(self.bak_src, self.target)
            return
        self._target_backup = self.target.with_suffix(
            self.target.suffix + ".preinstall-tmp"
        )
        shutil.copy2(self.target, self._target_backup)

        cur = json.loads(self.target.read_text())
        bak = json.loads(self.bak_src.read_text())
        cur_allow = (cur.get("permissions") or {}).get("allow") or []
        bak_allow = (bak.get("permissions") or {}).get("allow") or []
        merged = sorted({*cur_allow, *bak_allow})
        cur.setdefault("permissions", {})["allow"] = merged
        self.target.write_text(json.dumps(cur, indent=2) + "\n")

    def rollback(self) -> None:
        if self._target_backup and self._target_backup.exists():
            shutil.move(str(self._target_backup), str(self.target))
        elif self.target.exists():
            # Target didn't exist before — remove the copy we placed.
            if not self._target_backup:
                self.target.unlink()


# ---------------------------------------------------------------------------
# Installer
# ---------------------------------------------------------------------------


@dataclass
class InstallResult:
    backups: dict[Path, Path] = field(default_factory=dict)
    operations: list[Op] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    rolled_back: bool = False
    error: Exception | None = None
    # Post-install reconcile guide (only when a real ~/.claude was moved aside).
    leftovers: list[str] = field(default_factory=list)
    reconcile_report: Path | None = None


class Installer:
    def __init__(
        self,
        home: Path,
        repo_root: Path,
        dry_run: bool = False,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self.home = home.resolve()
        self.repo_root = repo_root.resolve()
        self.dry_run = dry_run
        self.log = log or (lambda msg: print(msg))
        self.ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.result = InstallResult()
        self.shared_memory = self.repo_root / SHARED_MEMORY_REL

    # ---- public entry point ----

    def install(self) -> InstallResult:
        try:
            self._phase1_symlinks()
            self._phase2_memory()
            self._phase3_restore()
        except Exception as exc:
            self.log(f"FATAL: {exc}")
            self.log("rolling back...")
            self._rollback()
            self.result.error = exc
            self.result.rolled_back = True
            raise
        # Install succeeded. Leave a human-readable guide for whatever Phase 3
        # could not carry over — best-effort, never fails the install.
        try:
            self._write_reconcile_guide()
        except Exception as exc:  # noqa: BLE001
            self.log(f"warning: reconcile guide not written: {exc}")
        return self.result

    # ---- phase 1: top-level symlinks ----

    def _phase1_symlinks(self) -> None:
        (self.home / ".config").mkdir(parents=True, exist_ok=True)

        for home_rel, repo_rel in LINK_PATHS:
            target = self.home / home_rel
            source = self.repo_root / repo_rel

            if target.is_symlink():
                if Path(os.readlink(target)) == source:
                    self.result.skipped.append(f"already linked: {target}")
                    continue
                # Foreign symlink — remove it before installing ours.
                self._record(_Unlink(target))
            elif target.exists():
                backup = target.with_name(target.name + f".bak.{self.ts}")
                self.result.backups[target] = backup
                self._record(Backup(target, backup))

            self._record(Symlink(source, target))

    # ---- phase 2: memory unification ----

    def _phase2_memory(self) -> None:
        claude_bak = self.result.backups.get(self.home / ".claude")
        slugs = self._discover_slugs(claude_bak)

        for slug in slugs:
            mem_link = self.home / MEMORY_PARENT / slug / "memory"
            parent = mem_link.parent

            bak_mem = (
                claude_bak / "projects" / slug / "memory" if claude_bak else None
            )
            if bak_mem and bak_mem.is_dir():
                self._record(MergeMissingFiles(bak_mem, self.shared_memory))

            self._record(Mkdir(parent))

            if mem_link.is_symlink():
                if Path(os.readlink(mem_link)) == self.shared_memory:
                    continue
                self._record(_Unlink(mem_link))
            elif mem_link.exists():
                backup = mem_link.with_name(mem_link.name + f".bak.{self.ts}")
                self._record(Backup(mem_link, backup))

            self._record(Symlink(self.shared_memory, mem_link))

    def _discover_slugs(self, claude_bak: Path | None) -> list[str]:
        slugs: list[str] = []
        if claude_bak and (claude_bak / "projects").is_dir():
            for sub in (claude_bak / "projects").iterdir():
                if (sub / "memory").exists():
                    slugs.append(sub.name)

        cwd_slug = str(Path.cwd()).replace("/", "-")
        if cwd_slug not in slugs:
            slugs.append(cwd_slug)
        return slugs

    # ---- phase 3: restore runtime data ----

    def _phase3_restore(self) -> None:
        claude_bak = self.result.backups.get(self.home / ".claude")
        if not claude_bak or not claude_bak.is_dir():
            self.result.skipped.append("phase 3: no fresh ~/.claude backup")
            return

        cur = self.home / ".claude"

        # .credentials.json — copy if missing
        cred_src = claude_bak / ".credentials.json"
        if cred_src.exists() and not (cur / ".credentials.json").exists():
            self._record(CopyFile(cred_src, cur / ".credentials.json"))

        # history.jsonl — prepend backup onto current (or copy)
        hist_src = claude_bak / "history.jsonl"
        if hist_src.exists():
            self._record(ConcatFile(hist_src, cur / "history.jsonl"))

        # sessions/ — copy whole tree if absent
        sess_src = claude_bak / "sessions"
        if sess_src.is_dir() and not (cur / "sessions").exists():
            self._record(CopyTree(sess_src, cur / "sessions"))

        # file-history/ — merge missing files only
        fh_src = claude_bak / "file-history"
        if fh_src.is_dir():
            self._record(MergeMissingFiles(fh_src, cur / "file-history"))

        # per-project transcripts
        projects = claude_bak / "projects"
        if projects.is_dir():
            for proj in projects.iterdir():
                if not proj.is_dir():
                    continue
                dest = cur / "projects" / proj.name
                transcripts = sorted(proj.glob("*.jsonl"))
                if not transcripts:
                    continue
                self._record(Mkdir(dest))
                for t in transcripts:
                    if (dest / t.name).exists():
                        # Live UUID collision — park backup under .bak suffix.
                        preserved = dest / f"{t.stem}.pre-install.jsonl.bak"
                        if not preserved.exists():
                            self._record(CopyFile(t, preserved))
                    else:
                        self._record(CopyFile(t, dest / t.name))

        # settings.local.json — merge permissions.allow
        sl_src = claude_bak / "settings.local.json"
        if sl_src.exists():
            self._record(MergeJsonPermissions(sl_src, cur / "settings.local.json"))

    # ---- post-install: reconcile guide (never invokes claude) ----

    def _write_reconcile_guide(self) -> None:
        """Leave a guide for what Phase 3 did NOT carry over.

        Only runs when a real ``~/.claude`` was moved aside. Computes which
        top-level entries of the backup were actually migrated (by inspecting
        the recorded operations) and lists the rest, then writes a markdown
        guide into the backup with a ready-to-paste prompt so the user can open
        ``claude`` themselves and finish. Never runs claude; never touches the
        backup beyond writing this one file.
        """
        claude_bak = self.result.backups.get(self.home / ".claude")
        if self.dry_run or not claude_bak or not claude_bak.is_dir():
            return

        cur = (self.home / ".claude").resolve()
        migrated: set[str] = set()
        for op in self.result.operations:
            dst = getattr(op, "dst", None) or getattr(op, "target", None)
            if dst is None:
                continue
            try:
                rel = Path(dst).resolve().relative_to(cur)
            except ValueError:
                continue
            if rel.parts:
                migrated.add(rel.parts[0])

        leftovers = [
            child.name
            for child in sorted(claude_bak.iterdir())
            if child.name not in migrated
        ]
        self.result.leftovers = leftovers
        if not leftovers:
            return

        hints = {
            "settings.json": (
                "custom hooks/settings — only settings.local.json permissions "
                "were merged; merge any custom hooks by hand"
            ),
            "shell-snapshots": "captured shell env snapshots — usually safe to drop",
            "remote-settings.json": "managed/remote settings cache",
            "todos": "per-session todo lists",
            "statsig": "feature-flag cache — safe to drop",
            "plugins": "installed plugins/marketplaces — recheck if you rely on them",
        }

        report = claude_bak / "RECONCILE-WITH-CLAUDE.md"
        lines = [
            f"# Migration reconcile — {self.ts}",
            "",
            "`install.py` symlinked your home config into this repo and moved your",
            "previous real `~/.claude` here:",
            "",
            f"    {claude_bak}",
            "",
            "Phase 3 auto-carried the important runtime data (transcripts, history,",
            "sessions, file-history, credentials, settings.local permissions) into the",
            "new `~/.claude`. The items below were **not** carried over and remain",
            "only in this backup — review and move anything you still want by hand.",
            "",
            "## Not auto-migrated (review)",
            "",
        ]
        lines += [
            f"- `{name}`" + (f" — {hints[name]}" if name in hints else "")
            for name in leftovers
        ]
        lines += [
            "",
            "## Finish it yourself with Claude",
            "",
            "Open Claude in the repo:",
            "",
            f"    cd {self.repo_root}",
            "    claude",
            "",
            "Then paste:",
            "",
            "> Reconcile my Claude migration. Compare the backup at",
            f"> `{claude_bak}` against my current `~/.claude` and help me carry over",
            "> anything important that was not migrated (list is in this file:",
            f"> `{report}`). Do NOT delete the backup; show me each move first.",
            "",
            "_Delete the backup only after you have confirmed nothing else is needed._",
            "",
        ]
        report.write_text("\n".join(lines))
        self.result.reconcile_report = report

    # ---- internals ----

    def _record(self, op: Op) -> None:
        if self.dry_run:
            self.log(f"DRY: {op.description}")
            return
        self.log(f"RUN: {op.description}")
        op.apply()
        self.result.operations.append(op)

    def _rollback(self) -> None:
        for op in reversed(self.result.operations):
            try:
                op.rollback()
            except Exception as exc:  # noqa: BLE001
                self.log(f"  rollback failed for {op}: {exc}")


@dataclass
class _Unlink(Op):
    """Symlink removal with the readlink target captured for rollback."""

    path: Path
    _was_symlink: bool = field(default=False, init=False)
    _orig_target: Path | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self.description = f"rm-symlink {self.path}"

    def apply(self) -> None:
        if self.path.is_symlink():
            self._was_symlink = True
            self._orig_target = Path(os.readlink(self.path))
            self.path.unlink()

    def rollback(self) -> None:
        if self._was_symlink and self._orig_target is not None:
            if self.path.exists() or self.path.is_symlink():
                return
            self.path.symlink_to(self._orig_target)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def install(
    home: Path | None = None,
    repo_root: Path | None = None,
    dry_run: bool = False,
    log: Callable[[str], None] | None = None,
) -> InstallResult:
    """Library entry point. Returns InstallResult; raises on failure."""
    home = home or Path.home()
    repo_root = repo_root or Path(__file__).resolve().parent.parent
    return Installer(home=home, repo_root=repo_root, dry_run=dry_run, log=log).install()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Install agents harness symlinks.")
    p.add_argument("--dry-run", action="store_true", help="preview without changes")
    p.add_argument("--home", type=Path, default=None, help="override $HOME")
    p.add_argument("--repo", type=Path, default=None, help="override repo root")
    args = p.parse_args(argv)

    try:
        result = install(home=args.home, repo_root=args.repo, dry_run=args.dry_run)
    except Exception as exc:  # noqa: BLE001
        print(f"\ninstall failed: {exc}", file=sys.stderr)
        return 1

    if result.skipped:
        for msg in result.skipped:
            print(f"SKIP: {msg}")

    if result.reconcile_report:
        print()
        print("Some items were not auto-migrated. Open `claude` and finish them:")
        print(f"  guide: {result.reconcile_report}")

    print()
    print("Done. Run 'scripts/doctor.sh' to verify.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
