"""Tests for the doctor tool."""

from __future__ import annotations

import os
import unittest

from tests._helpers import TmpRepoTestCase, install_doctor_stub
from integrated_harness_kit_mcp.tools.doctor import doctor


class DoctorTestCase(TmpRepoTestCase):
    def test_returns_error_when_repo_missing(self):
        # Point at a directory that isn't a valid repo.
        original = os.environ.pop("AGENTS_REPO", None)
        try:
            result = doctor(repo_path=str(self.tmp_path / "nope"))
            self.assertFalse(result["ok"])
            self.assertEqual(result["exit_code"], -1)
            self.assertIn("not found", result["stderr"])
        finally:
            if original is not None:
                os.environ["AGENTS_REPO"] = original

    def test_returns_error_when_script_missing(self):
        # Repo exists but no doctor.sh inside.
        result = doctor(repo_path=str(self.repo))
        self.assertFalse(result["ok"])
        self.assertEqual(result["exit_code"], -1)
        self.assertIn("missing script", result["stderr"])

    def test_runs_passing_doctor(self):
        install_doctor_stub(self.repo)
        result = doctor(repo_path=str(self.repo))
        self.assertTrue(result["ok"])
        self.assertEqual(result["exit_code"], 0)
        self.assertIn("doctor: all checks passed", result["stdout"])

    def test_runs_failing_doctor(self):
        install_doctor_stub(
            self.repo,
            body='#!/usr/bin/env bash\necho "FAIL bad thing" >&2\nexit 7\n',
        )
        result = doctor(repo_path=str(self.repo))
        self.assertFalse(result["ok"])
        self.assertEqual(result["exit_code"], 7)
        self.assertIn("FAIL bad thing", result["stderr"])

    def test_timeout(self):
        install_doctor_stub(
            self.repo,
            body='#!/usr/bin/env bash\nsleep 3\n',
        )
        result = doctor(repo_path=str(self.repo), timeout=0.5)
        self.assertFalse(result["ok"])
        self.assertEqual(result["exit_code"], -2)
        self.assertIn("exceeded", result["stderr"])


if __name__ == "__main__":
    unittest.main()
