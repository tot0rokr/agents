"""layout — the classification every other tool depends on."""

from __future__ import annotations

import json

from tests._helpers import HarnessTestCase, make_overlay, register_and_install


class ClassifyTests(HarnessTestCase):
    def setUp(self) -> None:
        super().setUp()
        from integrated_harness_kit_mcp import layout

        self.layout = layout
        make_overlay(
            self.repo,
            "work",
            priority=60,
            memories={"secret_host": "---\nname: secret_host\n---\n\nInternal.\n"},
        )
        register_and_install(self.repo, "work", priority=60)

    def test_artifact_is_not_writable(self):
        self.assertEqual(self.layout.classify(self.repo, "claude/settings.json"), "artifact")
        ok, reason = self.layout.writable(self.repo, "claude/settings.json")
        self.assertFalse(ok)
        self.assertIn("settings.base.json", reason)

    def test_base_source_is_writable(self):
        self.assertEqual(self.layout.classify(self.repo, "claude/settings.base.json"), "base_source")
        self.assertEqual(self.layout.classify(self.repo, "shared/commands/foo.md"), "base_source")
        ok, _ = self.layout.writable(self.repo, "shared/commands/foo.md")
        self.assertTrue(ok)

    def test_overlay_owned_symlink_is_detected(self):
        rel = "shared/memory/secret_host.md"
        self.assertTrue((self.repo / rel).is_symlink())
        self.assertEqual(self.layout.classify(self.repo, rel), "overlay_owned")
        self.assertEqual(
            self.layout.provenance(self.repo, rel), {"kind": "overlay", "alias": "work"}
        )
        ok, reason = self.layout.writable(self.repo, rel)
        self.assertFalse(ok)
        self.assertIn("work", reason)

    def test_overlay_dir_itself_is_overlay_owned(self):
        self.assertEqual(
            self.layout.classify(self.repo, "overlays/work/memory/secret_host.md"), "overlay_owned"
        )

    def test_credentials_and_build_output(self):
        self.assertEqual(self.layout.classify(self.repo, "overlays/work/secrets/x.env"), "credential")
        self.assertEqual(self.layout.classify(self.repo, ".pypirc"), "credential")
        self.assertEqual(self.layout.classify(self.repo, "mcp/dist/pkg.whl"), "build_artifact")

    def test_public_rendered_configs_are_artifacts(self):
        for rel in ("codex/config.toml", "gemini/settings.json", "opencode/opencode.json"):
            self.assertEqual(self.layout.classify(self.repo, rel), "artifact", rel)

    def test_base_provenance_when_not_overlaid(self):
        (self.repo / "shared" / "commands" / "own.md").write_text("---\ndescription: x\n---\n")
        self.assertEqual(
            self.layout.provenance(self.repo, "shared/commands/own.md"), {"kind": "base"}
        )

    def test_registry_is_priority_ordered(self):
        make_overlay(self.repo, "personal", priority=10)
        register_and_install(self.repo, "personal", priority=10)
        aliases = [entry["alias"] for entry in self.layout.registered_overlays(self.repo)]
        self.assertEqual(aliases, ["personal", "work"])

    def test_applied_links_maps_paths_to_aliases(self):
        links = self.layout.applied_links(self.repo)
        self.assertEqual(links.get("shared/memory/secret_host.md"), "work")

    def test_supports_overlays(self):
        self.assertTrue(self.layout.supports_overlays(self.repo))

    def test_read_json_survives_garbage(self):
        bad = self.repo / "bad.json"
        bad.write_text("{not json")
        self.assertEqual(self.layout.read_json(bad), {})
        self.assertEqual(self.layout.read_json(self.repo / "nope.json"), {})


class LegacyRepoTests(HarnessTestCase):
    """A repo from before overlays must still classify sensibly."""

    with_scripts = False

    def test_no_overlay_support(self):
        from integrated_harness_kit_mcp import layout

        self.assertFalse(layout.supports_overlays(self.repo))
        self.assertEqual(layout.applied_links(self.repo), {})
        self.assertEqual(layout.provenance(self.repo, "shared/commands/x.md"), {"kind": "base"})


class SettingsFixtureTests(HarnessTestCase):
    def test_bases_written(self):
        data = json.loads((self.repo / "claude" / "settings.base.json").read_text())
        self.assertEqual(data["model"], "test-model")
