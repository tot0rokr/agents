"""Tests for the harness_status tool."""

from __future__ import annotations

import os
import unittest

from tests._helpers import TmpRepoTestCase
from harness_adapter_mcp.tools.status import harness_status


_LINK_PATHS = [
    (".claude", "claude"),
    (".codex", "codex"),
    (".config/opencode", "opencode"),
    (".gemini", "gemini"),
    (".agents", "universal"),
]


class StatusTestCase(TmpRepoTestCase):
    def _install_all_symlinks(self):
        """Mirror what install.py would produce in this fake home."""
        (self.home / ".config").mkdir(exist_ok=True)
        for h_rel, r_rel in _LINK_PATHS:
            target = self.home / h_rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(self.repo / r_rel)

    def test_reports_missing_when_nothing_installed(self):
        result = harness_status(home=str(self.home), repo_path=str(self.repo))
        self.assertFalse(result["installed"])
        self.assertEqual(result["repo"], str(self.repo.resolve()))
        states = {l["expected_repo_sub"]: l["state"] for l in result["links"]}
        self.assertTrue(all(s == "missing" for s in states.values()))

    def test_reports_installed_when_all_symlinks_match(self):
        self._install_all_symlinks()
        result = harness_status(home=str(self.home), repo_path=str(self.repo))
        self.assertTrue(result["installed"])
        self.assertEqual(result["repo"], str(self.repo.resolve()))
        for link in result["links"]:
            self.assertEqual(link["state"], "linked")

    def test_detects_foreign_symlink(self):
        elsewhere = self.tmp_path / "elsewhere"
        elsewhere.mkdir()
        (self.home / ".claude").symlink_to(elsewhere)

        result = harness_status(home=str(self.home), repo_path=str(self.repo))
        claude = next(l for l in result["links"] if l["path"].endswith("/.claude"))
        self.assertEqual(claude["state"], "linked-elsewhere")
        self.assertEqual(claude["target"], str(elsewhere))
        self.assertFalse(result["installed"])

    def test_detects_real_dir(self):
        (self.home / ".claude").mkdir()
        result = harness_status(home=str(self.home), repo_path=str(self.repo))
        claude = next(l for l in result["links"] if l["path"].endswith("/.claude"))
        self.assertEqual(claude["state"], "real-dir")

    def test_repo_not_found(self):
        bogus = self.tmp_path / "missing"
        # Don't make a real repo at bogus path.
        # Ensure env doesn't sneak in.
        original = os.environ.pop("AGENTS_REPO", None)
        try:
            result = harness_status(home=str(self.home), repo_path=str(bogus))
            self.assertIsNone(result["repo"])
            self.assertFalse(result["installed"])
        finally:
            if original is not None:
                os.environ["AGENTS_REPO"] = original


if __name__ == "__main__":
    unittest.main()
