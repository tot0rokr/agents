"""bootstrap — the whole sequence a fresh machine needs."""

from __future__ import annotations

from tests._helpers import HarnessTestCase, install_doctor_stub, make_overlay, overlay_cli


class BootstrapTests(HarnessTestCase):
    def setUp(self) -> None:
        super().setUp()
        from integrated_harness_kit_mcp.tools import bootstrap as bootstrap_mod

        self.bootstrap = bootstrap_mod.bootstrap
        install_doctor_stub(self.repo)

    def run_bootstrap(self, **kwargs):
        return self.bootstrap(dest=str(self.repo), home=str(self.home), **kwargs)

    def steps(self, result) -> dict:
        return {step["step"]: step for step in result["steps"]}

    def test_existing_repo_skips_the_clone(self):
        result = self.run_bootstrap(dry_run=True)
        clone = self.steps(result)["clone"]
        self.assertTrue(clone["ok"])
        self.assertIn("already present", clone["skipped"])

    def test_dry_run_stops_after_install(self):
        result = self.run_bootstrap(dry_run=True)
        self.assertEqual(list(self.steps(result)), ["clone", "install"])

    def test_full_run_installs_renders_and_verifies(self):
        result = self.run_bootstrap()
        names = list(self.steps(result))
        self.assertEqual(names, ["clone", "install", "render", "overlays", "verify"])
        self.assertTrue((self.home / ".claude").is_symlink())
        self.assertTrue((self.repo / "claude" / "settings.json").is_file())
        self.assertTrue(result["ok"], result)

    def test_overlays_step_reports_when_none_are_registered(self):
        result = self.run_bootstrap()
        overlays = self.steps(result)["overlays"]
        self.assertTrue(overlays["ok"])
        self.assertEqual(overlays["skipped"], "none registered")
        self.assertIn("overlay_add", overlays["hint"])

    def test_registered_overlays_are_applied(self):
        make_overlay(
            self.repo,
            "work",
            priority=60,
            memories={"internal": "---\nname: internal\n---\n\nx\n"},
        )
        overlay_cli(self.repo, "add", "work", "--priority", "60")
        result = self.run_bootstrap()
        self.assertTrue(self.steps(result)["overlays"]["ok"], result)
        self.assertTrue((self.repo / "shared" / "memory" / "internal.md").is_symlink())

    def test_a_failed_install_stops_the_sequence(self):
        (self.repo / "scripts" / "install.py").write_text("import sys; sys.exit(3)\n")
        result = self.run_bootstrap()
        self.assertFalse(result["ok"])
        self.assertEqual(list(self.steps(result)), ["clone", "install"])
