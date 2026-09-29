"""Manifest priority on add, and an overlay's machine-only *.local.json fragments."""

from __future__ import annotations

import json
import subprocess

from tests._helpers import HarnessTestCase, _git, make_overlay, overlay_cli

AUTO_SHARED = {"autoMode": {"environment": ["shared: another machine"]}}
AUTO_LOCAL = {"autoMode": {"environment": ["local: this machine"]}}


def _registry(repo) -> dict[str, int]:
    data = json.loads((repo / "overlays" / "registry.local.json").read_text())
    return {e["alias"]: e["priority"] for e in data["overlays"]}


def _settings(repo) -> dict:
    return json.loads((repo / "claude" / "settings.json").read_text())


def _write_local(overlay_root, rel: str, data: dict) -> None:
    path = overlay_root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def _ok(proc: subprocess.CompletedProcess) -> subprocess.CompletedProcess:
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc


class ManifestPriorityTests(HarnessTestCase):
    def test_add_without_flag_takes_the_manifest_priority(self):
        make_overlay(self.repo, "work", priority=60)
        proc = _ok(overlay_cli(self.repo, "add", "work"))
        self.assertIn("priority 60", proc.stdout)
        self.assertEqual(_registry(self.repo), {"work": 60})

    def test_flag_overrides_the_manifest(self):
        make_overlay(self.repo, "work", priority=60)
        _ok(overlay_cli(self.repo, "add", "work", "--priority", "70"))
        self.assertEqual(_registry(self.repo), {"work": 70})

    def test_flag_zero_is_honoured_not_treated_as_missing(self):
        make_overlay(self.repo, "work", priority=60)
        _ok(overlay_cli(self.repo, "add", "work", "--priority", "0"))
        self.assertEqual(_registry(self.repo), {"work": 0})

    def test_a_non_integer_manifest_priority_is_a_clean_error(self):
        for n, bad in enumerate(("high", None, 1.5, True)):
            with self.subTest(priority=bad):
                root = make_overlay(self.repo, f"bad{n}")
                manifest = json.loads((root / "overlay.json").read_text())
                manifest["priority"] = bad
                (root / "overlay.json").write_text(json.dumps(manifest) + "\n")
                proc = overlay_cli(self.repo, "add", root.name)
                self.assertNotEqual(proc.returncode, 0)
                self.assertNotIn("Traceback", proc.stderr)
                self.assertIn("priority must be an integer", proc.stdout + proc.stderr)
                ok = overlay_cli(self.repo, "add", root.name, "--priority", "55")
                self.assertEqual(ok.returncode, 0, "--priority is the documented way out")

    def test_manifest_without_priority_falls_back_to_50(self):
        root = make_overlay(self.repo, "work")
        manifest = json.loads((root / "overlay.json").read_text())
        del manifest["priority"]
        (root / "overlay.json").write_text(json.dumps(manifest) + "\n")
        _ok(overlay_cli(self.repo, "add", "work"))
        self.assertEqual(_registry(self.repo), {"work": 50})

    def test_manifest_priority_decides_a_contested_key(self):
        # Before the fix both registered at 50 and the tie went to the later
        # alias, so "zz-personal" beat "aa-work" despite the manifests.
        make_overlay(self.repo, "aa-work", priority=60, settings={"model": "work"})
        make_overlay(self.repo, "zz-personal", priority=50, settings={"model": "personal"})
        for alias in ("aa-work", "zz-personal"):
            _ok(overlay_cli(self.repo, "add", alias))
        _ok(overlay_cli(self.repo, "install"))
        self.assertEqual(_settings(self.repo)["model"], "work")

    def test_mcp_overlay_add_defers_to_the_manifest(self):
        from integrated_harness_kit_mcp.tools import overlay

        make_overlay(self.repo, "work", priority=60)
        result = overlay.overlay_add("work", repo_path=str(self.repo))
        self.assertTrue(result["ok"], result)
        self.assertEqual(_registry(self.repo), {"work": 60})

    def test_mcp_overlay_add_explicit_priority_still_wins(self):
        from integrated_harness_kit_mcp.tools import overlay

        make_overlay(self.repo, "work", priority=60)
        self.assertTrue(overlay.overlay_add("work", priority=40, repo_path=str(self.repo))["ok"])
        self.assertEqual(_registry(self.repo), {"work": 40})


class LocalFragmentTests(HarnessTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.work = make_overlay(self.repo, "work", priority=60, settings=AUTO_SHARED)
        _ok(overlay_cli(self.repo, "add", "work"))

    def _install(self) -> dict:
        _ok(overlay_cli(self.repo, "install"))
        return _settings(self.repo)

    def test_local_fragment_overrides_its_own_overlay(self):
        _write_local(self.work, "settings/claude.local.json", AUTO_LOCAL)
        self.assertEqual(self._install()["autoMode"], AUTO_LOCAL["autoMode"])

    def test_without_a_local_fragment_the_shared_one_applies(self):
        self.assertEqual(self._install()["autoMode"], AUTO_SHARED["autoMode"])

    def test_deleting_the_local_fragment_falls_back_to_the_shared_one(self):
        _write_local(self.work, "settings/claude.local.json", {**AUTO_LOCAL, "onlyLocal": 1})
        self._install()
        (self.work / "settings" / "claude.local.json").unlink()
        settings = self._install()
        self.assertEqual(settings["autoMode"], AUTO_SHARED["autoMode"])
        self.assertNotIn("onlyLocal", settings, "a key only the deleted file set must not linger")

    def test_local_fragment_alone_is_enough(self):
        (self.work / "settings" / "claude.json").unlink()
        _write_local(self.work, "settings/claude.local.json", AUTO_LOCAL)
        self.assertEqual(self._install()["autoMode"], AUTO_LOCAL["autoMode"])

    def test_lower_overlays_local_does_not_beat_a_higher_overlays_shared(self):
        low = make_overlay(self.repo, "personal", priority=50, settings={"model": "low-shared"})
        _write_local(low, "settings/claude.local.json", {"model": "low-local"})
        _write_local(self.work, "settings/claude.json", {"model": "high-shared"})
        _ok(overlay_cli(self.repo, "add", "personal"))
        self.assertEqual(self._install()["model"], "high-shared")

    def test_local_fragment_substitutes_vars(self):
        (self.work / "vars.json").write_text(json.dumps({"HOST": "rig-7"}) + "\n")
        _write_local(self.work, "settings/claude.local.json", {"env": {"RIG": "${HOST}"}})
        env = self._install()["env"]
        self.assertEqual(env["RIG"], "rig-7")
        self.assertEqual(env["KEEP"], "base", "objects still merge key by key")

    def test_runtime_keys_survive_next_to_a_local_fragment(self):
        _write_local(self.work, "settings/claude.local.json", AUTO_LOCAL)
        live = self._install()
        live["writtenByClaude"] = True
        (self.repo / "claude" / "settings.json").write_text(json.dumps(live) + "\n")
        settings = self._install()
        self.assertTrue(settings["writtenByClaude"])
        self.assertEqual(settings["autoMode"], AUTO_LOCAL["autoMode"])

    def test_removing_the_overlay_drops_what_only_its_local_fragment_set(self):
        _write_local(self.work, "settings/claude.local.json", {"onlyLocal": 1})
        self.assertEqual(self._install()["onlyLocal"], 1)
        _ok(overlay_cli(self.repo, "remove", "work"))
        settings = _settings(self.repo)
        self.assertNotIn("onlyLocal", settings)
        self.assertNotIn("autoMode", settings)

    def test_status_is_clean_then_sees_an_edited_local_fragment(self):
        _write_local(self.work, "settings/claude.local.json", AUTO_LOCAL)
        self._install()
        self.assertNotIn("DRIFT", overlay_cli(self.repo, "status").stdout)
        _write_local(self.work, "settings/claude.local.json", {"autoMode": {"environment": ["edited"]}})
        self.assertIn("DRIFT claude/settings.json", overlay_cli(self.repo, "status").stdout)

    def test_local_only_keys_are_still_allowed_in_overlay_fragments(self):
        proc = overlay_cli(self.repo, "install")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        check = subprocess.run(
            ["python3", str(self.repo / "scripts" / "render_settings.py"), "--check"],
            cwd=str(self.repo), capture_output=True, text=True,
        )
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)

    def test_mcp_servers_local_fragment_is_merged(self):
        _write_local(self.work, "mcp/servers.local.json", {"servers": {"rig": {"command": "/opt/rig"}}})
        self._install()
        servers = json.loads((self.repo / "shared" / "mcp" / "servers.json").read_text())["servers"]
        self.assertIn("rig", servers)
        self.assertIn("linear", servers, "the base's servers stay")

    def test_settings_get_names_the_local_fragment(self):
        from integrated_harness_kit_mcp.tools import settings

        _write_local(self.work, "settings/claude.local.json", AUTO_LOCAL)
        self._install()
        result = settings.settings_get("autoMode", repo_path=str(self.repo))
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["from"], "overlay:work:local")
        self.assertEqual(settings.settings_get("model", repo_path=str(self.repo))["from"], "base")


class LocalFragmentToolTests(HarnessTestCase):
    """The MCP write tools reach the local fragments the renderer merges."""

    def setUp(self) -> None:
        super().setUp()
        from integrated_harness_kit_mcp.tools import mcp_servers, settings

        self.settings, self.servers = settings, mcp_servers
        self.work = make_overlay(self.repo, "work", priority=60, settings={"model": "shared"})
        _ok(overlay_cli(self.repo, "add", "work"))
        _ok(overlay_cli(self.repo, "install"))

    def test_settings_set_writes_the_local_fragment(self):
        result = self.settings.settings_set(
            "autoMode", {"environment": ["mine"]}, target="overlay:work:local", repo_path=str(self.repo)
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["wrote"], "overlays/work/settings/claude.local.json")
        self.assertEqual(_settings(self.repo)["autoMode"], {"environment": ["mine"]})
        self.assertEqual(
            self.settings.settings_get("autoMode", repo_path=str(self.repo))["from"], "overlay:work:local"
        )

    def test_settings_set_remove_from_the_local_fragment(self):
        self.settings.settings_set("onlyHere", 1, target="overlay:work:local", repo_path=str(self.repo))
        result = self.settings.settings_set(
            "onlyHere", target="overlay:work:local", remove=True, repo_path=str(self.repo)
        )
        self.assertTrue(result["ok"], result)
        self.assertNotIn("onlyHere", _settings(self.repo))

    def test_writing_a_shadowed_key_to_the_shared_fragment_warns(self):
        self.settings.settings_set("model", "local", target="overlay:work:local", repo_path=str(self.repo))
        result = self.settings.settings_set("model", "new-shared", target="overlay:work", repo_path=str(self.repo))
        self.assertTrue(result["ok"], result)
        self.assertIn("claude.local.json", result.get("warning", ""))
        self.assertEqual(_settings(self.repo)["model"], "local", "the local file still wins")

    def test_unshadowed_shared_write_has_no_warning(self):
        result = self.settings.settings_set("model", "new-shared", target="overlay:work", repo_path=str(self.repo))
        self.assertNotIn("warning", result)
        self.assertEqual(_settings(self.repo)["model"], "new-shared")

    def test_base_refuses_local_only_keys_and_names_the_local_target(self):
        result = self.settings.settings_set("autoMode", {}, target="base", repo_path=str(self.repo))
        self.assertFalse(result["ok"])
        self.assertIn("overlay:<alias>:local", result["error"])

    def test_unknown_target_variants_are_rejected(self):
        for target in ("overlay:work:shared", "overlay:work:local:x", "overlay:nobody:local"):
            with self.subTest(target=target):
                self.assertFalse(
                    self.settings.settings_set("model", "x", target=target, repo_path=str(self.repo))["ok"]
                )
                self.assertFalse(
                    self.servers.mcp_server_set(
                        "kb", command="/opt/kb", target=target, repo_path=str(self.repo)
                    )["ok"]
                )

    def test_mcp_server_set_and_remove_in_the_local_fragment(self):
        added = self.servers.mcp_server_set(
            "rig", command="/opt/rig", env={"RIG_PASS": "p"}, target="overlay:work:local", repo_path=str(self.repo)
        )
        self.assertTrue(added["ok"], added)
        self.assertTrue((self.work / "mcp" / "servers.local.json").is_file())
        servers = json.loads((self.repo / "shared" / "mcp" / "servers.json").read_text())["servers"]
        self.assertIn("rig", servers)
        removed = self.servers.mcp_server_remove("rig", target="overlay:work:local", repo_path=str(self.repo))
        self.assertTrue(removed["ok"], removed)
        servers = json.loads((self.repo / "shared" / "mcp" / "servers.json").read_text())["servers"]
        self.assertNotIn("rig", servers)


class LocalFragmentStatusTests(HarnessTestCase):
    def test_status_flags_a_local_fragment_git_would_commit(self):
        work = make_overlay(self.repo, "work", priority=60)
        _ok(overlay_cli(self.repo, "add", "work"))
        _write_local(work, "settings/claude.local.json", AUTO_LOCAL)
        _ok(overlay_cli(self.repo, "install"))
        out = overlay_cli(self.repo, "status").stdout
        self.assertIn("LOCAL work/settings/claude.local.json is not gitignored", out)
        (work / ".gitignore").write_text("*.local.json\n")
        _git(work, "add", ".gitignore")
        _git(work, "-c", "user.name=t", "-c", "user.email=t@e", "commit", "-qm", "ignore local")
        proc = overlay_cli(self.repo, "status")
        self.assertNotIn("LOCAL", proc.stdout)
        self.assertEqual(proc.returncode, 0, proc.stdout)


class TemplateIgnoresLocalFragmentsTests(HarnessTestCase):
    def test_init_scaffold_keeps_local_fragments_out_of_git(self):
        _ok(overlay_cli(self.repo, "init", "fresh"))
        root = self.repo / "overlays" / "fresh"
        self.assertTrue((root / ".gitignore").is_file(), "copytree must carry the dotfile")
        _git(root, "init", "-q", "-b", "main")
        _write_local(root, "settings/claude.local.json", AUTO_LOCAL)
        ignored = _git(root, "check-ignore", "-q", "settings/claude.local.json")
        self.assertEqual(ignored.returncode, 0, "settings/claude.local.json must be ignored")
        tracked = _git(root, "check-ignore", "-q", "settings/claude.json")
        self.assertNotEqual(tracked.returncode, 0, "the shared fragment must stay trackable")
