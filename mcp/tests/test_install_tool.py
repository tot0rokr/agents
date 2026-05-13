"""Tests for the install tool — wraps scripts/install.py via subprocess."""

from __future__ import annotations

import unittest
from pathlib import Path

from tests._helpers import TmpRepoTestCase
from harness_adapter_mcp.tools.install_tool import install


_REAL_INSTALL_PY = (
    Path(__file__).resolve().parent.parent.parent / "scripts" / "install.py"
)


def _copy_install_py_into(repo: Path) -> None:
    """Copy the real install.py into the fake repo so the tool can run it."""
    target = repo / "scripts" / "install.py"
    target.write_text(_REAL_INSTALL_PY.read_text())
    target.chmod(0o755)
    # The real install.py expects more directories under repo than our
    # minimal fixture provides; create the missing ones.
    for sub in ("claude", "codex", "opencode", "gemini", "universal", "shared/memory"):
        (repo / sub).mkdir(parents=True, exist_ok=True)


class InstallToolTestCase(TmpRepoTestCase):
    def test_repo_missing(self):
        result = install(repo_path=str(self.tmp_path / "nope"))
        self.assertFalse(result["ok"])
        self.assertEqual(result["exit_code"], -1)
        self.assertIn("not found", result["stderr"])

    def test_dry_run_against_real_install_script(self):
        _copy_install_py_into(self.repo)
        fake_home = self.tmp_path / "home2"
        fake_home.mkdir()
        result = install(
            repo_path=str(self.repo),
            home=str(fake_home),
            dry_run=True,
        )
        self.assertTrue(result["ok"], msg=result.get("stderr"))
        self.assertEqual(result["exit_code"], 0)
        self.assertIn("DRY:", result["stdout"])

    def test_real_install_against_fake_home(self):
        _copy_install_py_into(self.repo)
        fake_home = self.tmp_path / "home3"
        fake_home.mkdir()
        result = install(repo_path=str(self.repo), home=str(fake_home))
        self.assertTrue(result["ok"], msg=result.get("stderr"))
        for sub in (".claude", ".codex", ".gemini", ".agents"):
            self.assertTrue((fake_home / sub).is_symlink())


if __name__ == "__main__":
    unittest.main()
