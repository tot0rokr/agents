"""overlay_* — the structured front for the repo's own overlay script."""

from __future__ import annotations

import json
import subprocess

from tests._helpers import HarnessTestCase, make_overlay, overlay_cli, register_and_install


class OverlayToolTests(HarnessTestCase):
    def setUp(self) -> None:
        super().setUp()
        from integrated_harness_kit_mcp.tools import overlay

        self.overlay = overlay
        make_overlay(
            self.repo,
            "work",
            priority=60,
            memories={"internal": "---\nname: internal\n---\n\nx\n"},
            manifest_extra={
                "claims": {"paths": [str(self.tmp_path / "workdir")], "remotes": ["*.internal"]}
            },
        )
        make_overlay(
            self.repo,
            "personal",
            priority=50,
            memories={"mine": "---\nname: mine\n---\n\nx\n"},
            manifest_extra={"claims": {"default": True}},
        )
        register_and_install(self.repo, "work", priority=60)
        register_and_install(self.repo, "personal", priority=50)

    def test_list_reports_priority_links_and_cleanliness(self):
        result = self.overlay.overlay_list(repo_path=str(self.repo))
        self.assertTrue(result["ok"], result)
        by_alias = {entry["alias"]: entry for entry in result["overlays"]}
        self.assertEqual(by_alias["work"]["priority"], 60)
        self.assertEqual(by_alias["work"]["links"], 1)
        self.assertTrue(by_alias["work"]["cloned"])
        self.assertFalse(by_alias["work"]["dirty"])

    def test_list_sees_a_dirty_overlay(self):
        (self.repo / "overlays" / "work" / "memory" / "scratch.md").write_text("x\n")
        by_alias = {
            entry["alias"]: entry
            for entry in self.overlay.overlay_list(repo_path=str(self.repo))["overlays"]
        }
        self.assertTrue(by_alias["work"]["dirty"])

    def test_route_picks_the_claiming_overlay(self):
        workdir = self.tmp_path / "workdir"
        workdir.mkdir()
        result = self.overlay.overlay_route(str(workdir), repo_path=str(self.repo))
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["alias"], "work")
        self.assertIn("workdir", result["explain"])

    def test_route_falls_back_to_the_default_overlay(self):
        other = self.tmp_path / "elsewhere"
        other.mkdir()
        result = self.overlay.overlay_route(str(other), repo_path=str(self.repo))
        self.assertEqual(result["alias"], "personal")

    def test_install_relinks_after_a_change(self):
        (self.repo / "overlays" / "work" / "memory" / "added.md").write_text("---\nname: added\n---\n")
        result = self.overlay.overlay_install("work", repo_path=str(self.repo))
        self.assertTrue(result["ok"], result)
        self.assertTrue((self.repo / "shared" / "memory" / "added.md").is_symlink())

    def test_remove_unlinks_and_forgets(self):
        result = self.overlay.overlay_remove("work", repo_path=str(self.repo))
        self.assertTrue(result["ok"], result)
        self.assertFalse((self.repo / "shared" / "memory" / "internal.md").exists())
        aliases = [e["alias"] for e in self.overlay.overlay_list(repo_path=str(self.repo))["overlays"]]
        self.assertEqual(aliases, ["personal"])

    def test_commit_inside_the_overlay(self):
        (self.repo / "overlays" / "work" / "memory" / "new.md").write_text("---\nname: new\n---\n")
        result = self.overlay.overlay_commit(
            "work", "add a memory", repo_path=str(self.repo)
        )
        self.assertTrue(result["ok"], result)
        self.assertIn("memory/new.md", result["files"])
        self.assertIn("add a memory", result["head"])

    def test_commit_refuses_an_empty_message_and_a_clean_tree(self):
        self.assertFalse(self.overlay.overlay_commit("work", "   ", repo_path=str(self.repo))["ok"])
        clean = self.overlay.overlay_commit("work", "nothing to do", repo_path=str(self.repo))
        self.assertFalse(clean["ok"])
        self.assertIn("nothing staged", clean["error"])

    def test_commit_refuses_a_path_outside_the_overlay(self):
        result = self.overlay.overlay_commit(
            "work", "sneaky", paths=["../../shared/memory"], repo_path=str(self.repo)
        )
        self.assertFalse(result["ok"])
        self.assertIn("escapes", result["error"])

    def test_commit_on_an_unknown_overlay(self):
        self.assertFalse(self.overlay.overlay_commit("ghost", "m", repo_path=str(self.repo))["ok"])

    def test_setup_defaults_to_a_dry_run(self):
        manifest = self.repo / "overlays" / "work" / "overlay.json"
        data = json.loads(manifest.read_text())
        marker = self.tmp_path / "setup-marker"
        data["setup"] = [
            {
                "id": "make-marker",
                "description": "creates a marker",
                "check": f"test -f {marker}",
                "run": f"touch {marker}",
            }
        ]
        manifest.write_text(json.dumps(data, indent=2))

        dry = self.overlay.overlay_setup("work", repo_path=str(self.repo))
        self.assertFalse(dry["executed"])
        self.assertIn("dry run", dry["stdout"])
        self.assertFalse(marker.exists())

        wet = self.overlay.overlay_setup("work", yes=True, repo_path=str(self.repo))
        self.assertTrue(wet["executed"])
        self.assertTrue(marker.exists())

    def test_add_registers_an_in_place_clone(self):
        make_overlay(self.repo, "third", priority=70)
        result = self.overlay.overlay_add("third", priority=70, repo_path=str(self.repo))
        self.assertTrue(result["ok"], result)
        aliases = [e["alias"] for e in self.overlay.overlay_list(repo_path=str(self.repo))["overlays"]]
        self.assertIn("third", aliases)

    def test_tools_degrade_when_the_repo_has_no_overlay_script(self):
        (self.repo / "scripts" / "overlay.py").unlink()
        result = self.overlay.overlay_list(repo_path=str(self.repo))
        self.assertFalse(result["ok"])
        self.assertIn("overlay.py", result["error"])


class OverlayCliSanityTests(HarnessTestCase):
    """The fixture itself must be exercising the real script."""

    def test_status_is_clean_after_install(self):
        make_overlay(self.repo, "work", priority=60)
        register_and_install(self.repo, "work", priority=60)
        proc: subprocess.CompletedProcess = overlay_cli(self.repo, "status")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("clean", proc.stdout)
