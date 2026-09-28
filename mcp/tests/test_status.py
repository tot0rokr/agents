"""status / capabilities — diagnostics, including on a repo without overlays."""

from __future__ import annotations

import os

from tests._helpers import HarnessTestCase, install_doctor_stub, make_overlay, register_and_install


class StatusTests(HarnessTestCase):
    def setUp(self) -> None:
        super().setUp()
        from integrated_harness_kit_mcp.tools import status as status_mod

        self.status = status_mod.status
        self.capabilities = status_mod.capabilities

    def test_missing_repo_is_reported(self):
        result = self.status(repo_path=str(self.tmp_path / "nowhere"))
        self.assertFalse(result["ok"])
        self.assertIn("not found", result["error"])

    def test_unknown_level(self):
        self.assertFalse(self.status(level="sideways", repo_path=str(self.repo))["ok"])

    def test_links_are_reported_as_missing_when_not_installed(self):
        result = self.status(repo_path=str(self.repo), home=str(self.home))
        states = {entry["path"].rsplit("/", 1)[1]: entry["state"] for entry in result["links"]}
        self.assertEqual(states[".claude"], "missing")
        self.assertFalse(result["ok"])

    def test_artifacts_report_whether_they_are_rendered(self):
        result = self.status(repo_path=str(self.repo))
        artifacts = {entry["path"]: entry for entry in result["artifacts"]}
        self.assertFalse(artifacts["claude/settings.json"]["rendered"])
        self.assertTrue(artifacts["claude/settings.json"]["source_present"])

    def test_overlays_are_listed_once_installed(self):
        make_overlay(self.repo, "work", priority=60, memories={"m": "---\nname: m\n---\n"})
        register_and_install(self.repo, "work", priority=60)
        result = self.status(repo_path=str(self.repo))
        self.assertTrue(result["overlays"]["supported"])
        entry = result["overlays"]["installed"][0]
        self.assertEqual(entry["alias"], "work")
        self.assertEqual(entry["links"], 1)

    def test_full_level_runs_doctor(self):
        install_doctor_stub(self.repo)
        result = self.status(level="full", repo_path=str(self.repo))
        self.assertIn("doctor", result)
        self.assertTrue(result["doctor"]["ok"])
        self.assertIn("all checks passed", result["doctor"]["stdout"])

    def test_a_failing_doctor_makes_status_not_ok(self):
        install_doctor_stub(self.repo, "#!/usr/bin/env bash\necho nope\nexit 1\n")
        result = self.status(level="full", repo_path=str(self.repo))
        self.assertFalse(result["ok"])

    def test_missing_doctor_is_reported(self):
        result = self.status(level="full", repo_path=str(self.repo))
        self.assertFalse(result["doctor"]["ok"])

    def test_capabilities_describe_this_repo(self):
        caps = self.capabilities(repo_path=str(self.repo))
        self.assertTrue(caps["overlays"])
        self.assertTrue(caps["overlay_route"])
        self.assertTrue(caps["render_settings"])
        self.assertTrue(caps["render_memory"])

    def test_capabilities_on_a_repo_without_overlays(self):
        (self.repo / "scripts" / "overlay.py").unlink()
        (self.repo / "scripts" / "render_settings.py").unlink()
        from integrated_harness_kit_mcp import repo_scripts

        repo_scripts.clear_cache()
        caps = self.capabilities(repo_path=str(self.repo))
        self.assertFalse(caps["overlays"])
        self.assertFalse(caps["render_settings"])

    def test_capabilities_without_a_repo(self):
        caps = self.capabilities(repo_path=str(self.tmp_path / "nowhere"))
        self.assertIsNone(caps["repo"])
        self.assertFalse(caps["overlays"])


class InstalledLinkTests(HarnessTestCase):
    def test_a_correct_symlink_counts_as_linked(self):
        from integrated_harness_kit_mcp.tools import status as status_mod

        os.symlink(self.repo / "claude", self.home / ".claude")
        result = status_mod.status(repo_path=str(self.repo), home=str(self.home))
        states = {entry["path"].rsplit("/", 1)[1]: entry["state"] for entry in result["links"]}
        self.assertEqual(states[".claude"], "linked")
