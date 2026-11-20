"""Unit tests for install.py — stdlib unittest, no external deps.

Run from repo root:

    python3 -m unittest scripts.test_install -v

or:

    python3 scripts/test_install.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import install as install_mod  # noqa: E402
from install import LINK_PATHS, Symlink, install  # noqa: E402


def setup_fake_repo(root: Path) -> Path:
    repo = root / "repo"
    for sub in ("claude", "codex", "opencode", "gemini", "universal", "shared/memory"):
        (repo / sub).mkdir(parents=True)
    return repo


def setup_fake_home(root: Path) -> Path:
    home = root / "home"
    home.mkdir()
    return home


def link_target(path: Path) -> Path:
    return Path(os.readlink(path))


class InstallTestBase(unittest.TestCase):
    """Shared fixture: a tmp dir with fake home+repo, cwd switched into home."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self.repo = setup_fake_repo(self.tmp_path)
        self.home = setup_fake_home(self.tmp_path)

        self._cwd = os.getcwd()
        os.chdir(self.home)

        self._symlink_apply = Symlink.apply

    def tearDown(self) -> None:
        Symlink.apply = self._symlink_apply
        os.chdir(self._cwd)
        self._tmp.cleanup()


class TestFreshInstall(InstallTestBase):
    def test_creates_all_symlinks(self):
        result = install(home=self.home, repo_root=self.repo)

        for h_rel, r_rel in LINK_PATHS:
            target = self.home / h_rel
            self.assertTrue(target.is_symlink(), f"{target} should be a symlink")
            self.assertEqual(link_target(target), (self.repo / r_rel).resolve())

        # No project's memory is linked to the shared pool.
        self.assertFalse((self.repo / "claude" / "projects").exists())

        self.assertEqual(list(self.home.glob(".claude.bak.*")), [])
        self.assertFalse(result.rolled_back)
        self.assertIsNone(result.error)


class TestIdempotency(InstallTestBase):
    def test_rerun_is_noop(self):
        install(home=self.home, repo_root=self.repo)
        second = install(home=self.home, repo_root=self.repo)

        skips = [s for s in second.skipped if "already linked" in s]
        self.assertEqual(
            len(skips),
            len(LINK_PATHS),
            f"expected {len(LINK_PATHS)} skips, got {second.skipped}",
        )


class TestBackup(InstallTestBase):
    def test_real_dir_backed_up(self):
        claude = self.home / ".claude"
        claude.mkdir()
        (claude / "important.txt").write_text("data")

        install(home=self.home, repo_root=self.repo)

        self.assertTrue(claude.is_symlink())
        backups = list(self.home.glob(".claude.bak.*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / "important.txt").read_text(), "data")


class TestCodexConfigSeed(InstallTestBase):
    def test_pre_harness_codex_config_seeds_the_render(self):
        codex = self.home / ".codex"
        codex.mkdir()
        (codex / "config.toml").write_text('[projects."/work"]\ntrust_level = "trusted"\n')

        install(home=self.home, repo_root=self.repo)

        seeded = self.repo / "codex" / "config.toml"
        self.assertEqual(seeded.read_text(), '[projects."/work"]\ntrust_level = "trusted"\n')

    def test_an_existing_render_is_not_overwritten(self):
        codex = self.home / ".codex"
        codex.mkdir()
        (codex / "config.toml").write_text('model = "old"\n')
        (self.repo / "codex" / "config.toml").write_text('model = "current"\n')

        install(home=self.home, repo_root=self.repo)

        self.assertEqual((self.repo / "codex" / "config.toml").read_text(), 'model = "current"\n')


class TestPhase3Restore(InstallTestBase):
    def test_runtime_data_restored_into_new_home(self):
        claude = self.home / ".claude"
        claude.mkdir()
        (claude / ".credentials.json").write_text('{"token": "abc"}')
        (claude / "history.jsonl").write_text('{"line": "old"}\n')
        (claude / "sessions").mkdir()
        (claude / "sessions" / "s1.json").write_text("{}")
        proj = claude / "projects" / "-test-slug"
        proj.mkdir(parents=True)
        (proj / "abc.jsonl").write_text("conversation\n")
        (claude / "settings.local.json").write_text(
            json.dumps({"permissions": {"allow": ["WebFetch(example.com)"]}})
        )
        (self.repo / "claude" / "settings.local.json").write_text(
            json.dumps({"permissions": {"allow": ["Bash(ls)"]}})
        )

        install(home=self.home, repo_root=self.repo)

        new_cl = self.home / ".claude"
        self.assertEqual(
            (new_cl / ".credentials.json").read_text(), '{"token": "abc"}'
        )
        self.assertEqual((new_cl / "history.jsonl").read_text(), '{"line": "old"}\n')
        self.assertEqual((new_cl / "sessions" / "s1.json").read_text(), "{}")
        self.assertEqual(
            (new_cl / "projects" / "-test-slug" / "abc.jsonl").read_text(),
            "conversation\n",
        )

        merged = json.loads((new_cl / "settings.local.json").read_text())
        self.assertEqual(
            set(merged["permissions"]["allow"]),
            {"WebFetch(example.com)", "Bash(ls)"},
        )


class TestReconcileGuide(InstallTestBase):
    def _make_real_claude_with_leftovers(self) -> Path:
        claude = self.home / ".claude"
        claude.mkdir()
        # migrated by phase 3
        (claude / "history.jsonl").write_text("{}\n")
        (claude / "sessions").mkdir()
        (claude / "sessions" / "s1.json").write_text("{}")
        # NOT migrated -> should be listed as leftovers
        (claude / "shell-snapshots").mkdir()
        (claude / "shell-snapshots" / "snap.sh").write_text("echo hi")
        (claude / "settings.json").write_text('{"hooks": {}}')
        (claude / "remote-settings.json").write_text("{}")
        return claude

    def test_guide_lists_only_unmigrated(self):
        self._make_real_claude_with_leftovers()

        result = install(home=self.home, repo_root=self.repo)

        self.assertIsNotNone(result.reconcile_report)
        report = result.reconcile_report
        self.assertTrue(report.is_file())
        # guide lives inside the backup, never deletes it
        backups = list(self.home.glob(".claude.bak.*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(report.parent, backups[0])

        text = report.read_text()
        for expected in ("shell-snapshots", "settings.json", "remote-settings.json"):
            self.assertIn(expected, result.leftovers)
            self.assertIn(expected, text)
        for migrated in ("history.jsonl", "sessions"):
            self.assertNotIn(migrated, result.leftovers)
        # custom-hooks hint is present for settings.json
        self.assertIn("merge any custom hooks", text)

    def test_fresh_install_writes_no_guide(self):
        result = install(home=self.home, repo_root=self.repo)
        self.assertIsNone(result.reconcile_report)
        self.assertEqual(result.leftovers, [])

    def test_dry_run_writes_no_guide(self):
        self._make_real_claude_with_leftovers()
        result = install(home=self.home, repo_root=self.repo, dry_run=True)
        self.assertIsNone(result.reconcile_report)


class TestPhase2ProjectMemory(InstallTestBase):
    """A project's memory moves with the old ~/.claude to the same project, never to the shared pool."""

    def old_memory(self, project: str = "-old-project") -> Path:
        mem = self.home / ".claude" / "projects" / project / "memory"
        mem.mkdir(parents=True)
        (mem / "MEMORY.md").write_text("- [old](old.md) — from the old home\n")
        (mem / "old.md").write_text("old memory")
        return mem

    def test_it_lands_in_the_same_project_and_not_in_the_pool(self):
        self.old_memory()

        install(home=self.home, repo_root=self.repo)

        mem = self.repo / "claude" / "projects" / "-old-project" / "memory"
        self.assertFalse(mem.is_symlink())
        self.assertEqual((mem / "old.md").read_text(), "old memory")
        self.assertEqual((mem / "MEMORY.md").read_text(), "- [old](old.md) — from the old home\n")
        self.assertFalse((self.repo / "shared" / "memory" / "old.md").exists())

    def test_it_merges_into_a_memory_the_repo_already_has(self):
        self.old_memory()
        mem = self.repo / "claude" / "projects" / "-old-project" / "memory"
        mem.mkdir(parents=True)
        (mem / "MEMORY.md").write_text("- [new](new.md) — made here\n")
        (mem / "old.md").write_text("changed here")

        result = install(home=self.home, repo_root=self.repo)

        self.assertEqual(
            (mem / "MEMORY.md").read_text(),
            "- [new](new.md) — made here\n- [old](old.md) — from the old home\n",
        )
        self.assertEqual((mem / "old.md").read_text(), "changed here")
        self.assertTrue(any("old.md" in msg and "differs" in msg for msg in result.skipped), result.skipped)

    def test_a_rerun_links_no_project_to_the_pool(self):
        (self.home / ".claude").symlink_to(self.repo.resolve() / "claude")
        mem = self.repo / "claude" / "projects" / "-some-project" / "memory"
        mem.mkdir(parents=True)
        (mem / "note.md").write_text("project memory")

        lines: list[str] = []
        install(home=self.home, repo_root=self.repo, log=lines.append)

        self.assertFalse(mem.is_symlink())
        self.assertEqual((mem / "note.md").read_text(), "project memory")
        self.assertFalse(list((self.repo / "claude").glob("projects/*/memory.bak.*")))
        self.assertFalse(any("shared/memory" in line for line in lines), lines)

    def test_a_failure_puts_the_merged_index_back(self):
        self.old_memory()
        (self.home / ".claude" / "history.jsonl").write_text("{}\n")
        mem = self.repo / "claude" / "projects" / "-old-project" / "memory"
        mem.mkdir(parents=True)
        (mem / "MEMORY.md").write_text("- [new](new.md) — made here\n")

        original = install_mod.ConcatFile.apply

        def fail(op):
            raise RuntimeError("injected failure")

        install_mod.ConcatFile.apply = fail
        try:
            with self.assertRaises(RuntimeError):
                install(home=self.home, repo_root=self.repo)
        finally:
            install_mod.ConcatFile.apply = original

        self.assertEqual((mem / "MEMORY.md").read_text(), "- [new](new.md) — made here\n")
        self.assertFalse((mem / "old.md").exists())
        self.assertTrue((self.home / ".claude" / "projects" / "-old-project" / "memory" / "old.md").is_file())


class TestRollback(InstallTestBase):
    def _inject_failure_on_nth_symlink(self, n: int):
        original = Symlink.apply
        counter = {"n": 0}

        def maybe_fail(self):
            counter["n"] += 1
            if counter["n"] == n:
                raise RuntimeError("injected failure")
            original(self)

        Symlink.apply = maybe_fail

    def test_state_restored_after_failure(self):
        claude = self.home / ".claude"
        claude.mkdir()
        (claude / "important.txt").write_text("data")

        self._inject_failure_on_nth_symlink(3)

        with self.assertRaises(RuntimeError) as ctx:
            install(home=self.home, repo_root=self.repo)
        self.assertIn("injected failure", str(ctx.exception))

        self.assertTrue(claude.is_dir())
        self.assertFalse(claude.is_symlink())
        self.assertEqual((claude / "important.txt").read_text(), "data")
        self.assertEqual(list(self.home.glob(".claude.bak.*")), [])
        self.assertFalse((self.home / ".codex").exists())
        self.assertFalse((self.home / ".config" / "opencode").exists())

    def test_clean_install_works_after_rollback(self):
        claude = self.home / ".claude"
        claude.mkdir()
        (claude / "important.txt").write_text("data")

        self._inject_failure_on_nth_symlink(3)
        with self.assertRaises(RuntimeError):
            install(home=self.home, repo_root=self.repo)

        Symlink.apply = self._symlink_apply
        install(home=self.home, repo_root=self.repo)

        for h_rel, _ in LINK_PATHS:
            self.assertTrue((self.home / h_rel).is_symlink())


class TestDryRun(InstallTestBase):
    def test_dry_run_no_changes(self):
        claude = self.home / ".claude"
        claude.mkdir()
        (claude / "important.txt").write_text("data")

        install(home=self.home, repo_root=self.repo, dry_run=True)

        self.assertTrue(claude.is_dir())
        self.assertFalse(claude.is_symlink())
        self.assertEqual((claude / "important.txt").read_text(), "data")
        self.assertFalse((self.home / ".codex").exists())
        self.assertEqual(list(self.home.glob(".claude.bak.*")), [])
        self.assertFalse((self.home / ".config").exists())

    def test_dry_run_previews_what_a_real_claude_dir_would_carry_over(self):
        mem = self.home / ".claude" / "projects" / "-old-slug" / "memory"
        mem.mkdir(parents=True)
        (mem / "note.md").write_text("project memory")
        (self.home / ".claude" / "history.jsonl").write_text("{}\n")

        lines: list[str] = []
        install(home=self.home, repo_root=self.repo, dry_run=True, log=lines.append)

        text = "\n".join(lines)
        repo = self.repo.resolve()
        self.assertIn(f"merge-missing {mem.resolve()}/* -> {repo / 'claude/projects/-old-slug/memory'}/", text)
        self.assertNotIn("shared/memory", text)
        self.assertIn(f"concat {self.home.resolve() / '.claude/history.jsonl'} + {repo / 'claude/history.jsonl'}", text)
        self.assertFalse((self.repo / "claude" / "projects").exists())
        self.assertFalse((self.repo / "shared" / "memory" / "note.md").exists())

    def test_dry_run_previews_the_render_and_writes_nothing(self):
        (self.repo / "claude" / "settings.base.json").write_text(json.dumps({"model": "m"}))

        lines: list[str] = []
        install(home=self.home, repo_root=self.repo, dry_run=True, log=lines.append)

        self.assertIn("DRY: render claude/settings.json: 1 change(s)", lines)
        self.assertIn('DRY: render     + model = "m"', lines)
        self.assertFalse((self.repo / "claude" / "settings.json").exists())
        self.assertFalse((self.repo / "overlays").exists())


class TestGlobalConfig(InstallTestBase):
    def setUp(self) -> None:
        super().setUp()
        (self.repo / install_mod.GLOBAL_CONFIG_BASE_REL).write_text(
            json.dumps({"leftArrowOpensAgents": False})
        )
        self.claude_json = self.home / ".claude.json"

    def test_base_keys_win_and_runtime_state_is_kept(self):
        self.claude_json.write_text(
            json.dumps({"numStartups": 5, "leftArrowOpensAgents": True})
        )

        install(home=self.home, repo_root=self.repo)

        self.assertEqual(
            json.loads(self.claude_json.read_text()),
            {"numStartups": 5, "leftArrowOpensAgents": False},
        )
        self.assertEqual(self.claude_json.stat().st_mode & 0o777, 0o600)

    def test_fresh_machine_gets_the_file(self):
        install(home=self.home, repo_root=self.repo)

        self.assertEqual(
            json.loads(self.claude_json.read_text()), {"leftArrowOpensAgents": False}
        )

    def test_dry_run_leaves_the_file_alone(self):
        self.claude_json.write_text('{"leftArrowOpensAgents": true}')

        lines: list[str] = []
        install(home=self.home, repo_root=self.repo, dry_run=True, log=lines.append)

        self.assertEqual(self.claude_json.read_text(), '{"leftArrowOpensAgents": true}')
        self.assertIn(f"DRY: set leftArrowOpensAgents in {self.claude_json.resolve()}", lines)


if __name__ == "__main__":
    unittest.main(verbosity=2)
