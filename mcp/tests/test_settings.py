"""settings_get / settings_set — provenance and write routing."""

from __future__ import annotations

import json

from tests._helpers import HarnessTestCase, make_overlay, overlay_cli, register_and_install


class SettingsTests(HarnessTestCase):
    def setUp(self) -> None:
        super().setUp()
        from integrated_harness_kit_mcp.tools import settings

        self.settings = settings
        make_overlay(
            self.repo,
            "work",
            priority=60,
            settings={"autoMode": {"environment": ["internal"]}, "model": "work-model"},
        )
        register_and_install(self.repo, "work", priority=60)

    def live(self) -> dict:
        return json.loads((self.repo / "claude" / "settings.json").read_text())

    def get(self, key=None) -> dict:
        return self.settings.settings_get(key=key, repo_path=str(self.repo))

    def test_overlay_beats_base_on_a_shared_key(self):
        self.assertEqual(self.live()["model"], "work-model")
        result = self.get("model")
        self.assertEqual(result["value"], "work-model")
        self.assertEqual(result["from"], "overlay:work")

    def test_base_key_is_attributed_to_base(self):
        self.assertEqual(self.get("env.KEEP")["from"], "base")

    def test_runtime_key_is_attributed_to_runtime(self):
        live = self.live()
        live["someRuntimeFlag"] = True
        (self.repo / "claude" / "settings.json").write_text(json.dumps(live, indent=2) + "\n")
        self.assertEqual(self.get("someRuntimeFlag")["from"], "runtime")

    def test_missing_key_reports_not_set(self):
        result = self.get("nope")
        self.assertFalse(result["ok"])

    def test_listing_every_key_carries_provenance(self):
        keys = self.get()["keys"]
        self.assertEqual(keys["model"]["from"], "overlay:work")
        self.assertEqual(keys["autoMode"]["from"], "overlay:work")

    def test_set_on_base_writes_the_base_and_renders(self):
        result = self.settings.settings_set(
            "theme", "dark", target="base", repo_path=str(self.repo)
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["wrote"], "claude/settings.base.json")
        self.assertEqual(self.live()["theme"], "dark")
        self.assertEqual(self.get("theme")["from"], "base")

    def test_set_on_overlay_writes_the_fragment(self):
        result = self.settings.settings_set(
            "statusLine.type", "command", target="overlay:work", repo_path=str(self.repo)
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["wrote"], "overlays/work/settings/claude.json")
        self.assertEqual(self.live()["statusLine"]["type"], "command")
        self.assertEqual(self.get("statusLine.type")["from"], "overlay:work")

    def test_nested_keys_are_created(self):
        self.settings.settings_set(
            "permissions.defaultMode", "auto", target="base", repo_path=str(self.repo)
        )
        base = json.loads((self.repo / "claude" / "settings.base.json").read_text())
        self.assertEqual(base["permissions"]["defaultMode"], "auto")

    def test_local_only_keys_cannot_be_tracked(self):
        result = self.settings.settings_set(
            "autoMode", {"environment": []}, target="base", repo_path=str(self.repo)
        )
        self.assertFalse(result["ok"])
        self.assertIn("runtime state", result["error"])

    def test_remove_drops_the_key_and_re_renders(self):
        self.settings.settings_set("theme", "dark", target="base", repo_path=str(self.repo))
        result = self.settings.settings_set(
            "theme", target="base", remove=True, repo_path=str(self.repo)
        )
        self.assertTrue(result["ok"], result)
        self.assertNotIn("theme", self.live())

    def test_removing_an_absent_key_fails(self):
        result = self.settings.settings_set(
            "ghost", target="base", remove=True, repo_path=str(self.repo)
        )
        self.assertFalse(result["ok"])

    def test_unknown_overlay_is_rejected(self):
        result = self.settings.settings_set(
            "x", 1, target="overlay:nope", repo_path=str(self.repo)
        )
        self.assertFalse(result["ok"])

    def test_runtime_key_survives_a_render(self):
        live = self.live()
        live["preserveMe"] = {"deep": 1}
        (self.repo / "claude" / "settings.json").write_text(json.dumps(live, indent=2) + "\n")
        self.settings.settings_set("theme", "dark", target="base", repo_path=str(self.repo))
        self.assertEqual(self.live()["preserveMe"], {"deep": 1})

    def test_disabled_overlay_stops_contributing(self):
        overlay_cli(self.repo, "remove", "work")
        self.assertEqual(self.get("model")["from"], "base")
        self.assertEqual(self.live()["model"], "test-model")
