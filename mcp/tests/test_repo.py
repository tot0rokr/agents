"""Repo discovery tests — no harness library import to avoid mcp dep."""

from __future__ import annotations

import os
import unittest

from tests._helpers import TmpRepoTestCase, make_fake_repo
from integrated_harness_kit_mcp.repo import find_repo


class FindRepoTestCase(TmpRepoTestCase):
    def test_finds_via_explicit_arg(self):
        result = find_repo(self.repo)
        self.assertEqual(result, self.repo.resolve())

    def test_returns_none_when_not_a_repo(self):
        bogus = self.tmp_path / "not-a-repo"
        bogus.mkdir()
        self.assertIsNone(find_repo(bogus))

    def test_env_var_overrides_default(self):
        original = os.environ.pop("AGENTS_REPO", None)
        try:
            os.environ["AGENTS_REPO"] = str(self.repo)
            self.assertEqual(find_repo(), self.repo.resolve())
        finally:
            os.environ.pop("AGENTS_REPO", None)
            if original is not None:
                os.environ["AGENTS_REPO"] = original

    def test_explicit_beats_env(self):
        other = make_fake_repo(self.tmp_path / "other")
        original = os.environ.pop("AGENTS_REPO", None)
        try:
            os.environ["AGENTS_REPO"] = str(self.repo)
            self.assertEqual(find_repo(other), other.resolve())
        finally:
            os.environ.pop("AGENTS_REPO", None)
            if original is not None:
                os.environ["AGENTS_REPO"] = original

    def test_missing_marker_file_rejects(self):
        # Looks repo-shaped, but no scripts/install.py.
        (self.tmp_path / "fake-repo").mkdir()
        self.assertIsNone(find_repo(self.tmp_path / "fake-repo"))


if __name__ == "__main__":
    unittest.main()
