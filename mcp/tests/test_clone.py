"""Tests for the clone tool."""

from __future__ import annotations

import subprocess
import unittest

from tests._helpers import TmpRepoTestCase
from integrated_harness_kit_mcp.tools.clone import clone


def _git_available() -> bool:
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


class CloneTestCase(TmpRepoTestCase):
    def test_refuses_existing_dest(self):
        dest = self.tmp_path / "existing"
        dest.mkdir()
        result = clone(dest=str(dest), repo_url="https://example.invalid/x.git")
        self.assertFalse(result["ok"])
        self.assertEqual(result["exit_code"], -1)
        self.assertIn("already exists", result["stderr"])

    def test_missing_parent(self):
        result = clone(
            dest=str(self.tmp_path / "no" / "such" / "place"),
            repo_url="https://example.invalid/x.git",
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["exit_code"], -1)
        self.assertIn("parent directory", result["stderr"])

    @unittest.skipUnless(_git_available(), "git not installed")
    def test_clone_local_bundle(self):
        """Use a local git repo as the source so we don't hit the network."""
        src = self.tmp_path / "source"
        src.mkdir()
        subprocess.run(["git", "init", "-q", str(src)], check=True)
        (src / "README").write_text("hi\n")
        env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}
        subprocess.run(["git", "-C", str(src), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", str(src), "commit", "-q", "-m", "init"],
            check=True, env={**env, "PATH": "/usr/bin:/bin"},
        )

        dest = self.tmp_path / "cloned"
        result = clone(dest=str(dest), repo_url=str(src))
        self.assertTrue(result["ok"], msg=result.get("stderr"))
        self.assertEqual(result["exit_code"], 0)
        self.assertTrue((dest / "README").is_file())


if __name__ == "__main__":
    unittest.main()
