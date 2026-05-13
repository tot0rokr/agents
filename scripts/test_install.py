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

        cwd_slug = str(self.home.resolve()).replace("/", "-")
        mem_link = self.home / ".claude" / "projects" / cwd_slug / "memory"
        self.assertTrue(mem_link.is_symlink())
        self.assertEqual(link_target(mem_link), (self.repo / "shared/memory").resolve())

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


class TestPhase2SlugDiscovery(InstallTestBase):
    def test_slug_from_backup_is_linked(self):
        mem_dir = self.home / ".claude" / "projects" / "-other-slug" / "memory"
        mem_dir.mkdir(parents=True)
        (mem_dir / "foo.md").write_text("project memory")

        install(home=self.home, repo_root=self.repo)

        new_mem = self.home / ".claude" / "projects" / "-other-slug" / "memory"
        self.assertTrue(new_mem.is_symlink())
        self.assertEqual(
            link_target(new_mem), (self.repo / "shared/memory").resolve()
        )
        self.assertEqual(
            (self.repo / "shared/memory" / "foo.md").read_text(), "project memory"
        )


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
