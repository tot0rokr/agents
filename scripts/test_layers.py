"""Unit tests for layers.py and the base layer in overlay.py — stdlib unittest.

Run from repo root:

    python3 scripts/test_layers.py
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import layers as layers_mod  # noqa: E402
import overlay as overlay_mod  # noqa: E402
import render_settings as rs  # noqa: E402
from test_render_codex import FixtureRepo, git  # noqa: E402


class LayerFixture(FixtureRepo):
    def setUp(self) -> None:
        super().setUp()
        git(self.repo, "init", "-q", "-b", "main")
        self.write(rs.BASE_REL, json.dumps({"model": "base"}))

    def run_cmd(self, *argv: str) -> tuple[int, list[str]]:
        lines: list[str] = []
        args = overlay_mod.build_parser().parse_args(list(argv))
        return args.func(self.repo, args, lines.append), lines

    def base_steps(self, *steps: dict) -> None:
        self.write(layers_mod.BASE_MANIFEST_REL, json.dumps({"name": "base", "priority": 0, "setup": list(steps)}))


class LayerOrderTests(LayerFixture):
    def test_the_base_comes_first_then_enabled_overlays_by_priority(self):
        self.add_overlay("zeta", 60, {})
        self.add_overlay("alpha", 50, {})
        self.add_overlay("off", 70, {})
        self.registry[-1]["enabled"] = False
        self.save_registry()
        self.assertEqual([layer.alias for layer in layers_mod.layers(self.repo)], ["base", "alpha", "zeta"])

    def test_the_base_maps_overlay_paths_to_where_it_keeps_them(self):
        base = layers_mod.BaseLayer(self.repo)
        self.assertEqual(base.real_path(rs.FRAGMENT_REL), self.repo / rs.BASE_REL)
        self.assertEqual(base.real_path(rs.MCP_FRAGMENT_REL), self.repo / rs.MCP_BASE_REL)
        self.assertEqual(base.real_path(rs.MEMORY_FRAGMENT_REL), self.repo / rs.MEMORY_BASE_REL)
        self.assertEqual(base.real_path(rs.CODEX_FRAGMENT_REL), self.repo / rs.CODEX_BASE_REL)
        self.assertEqual(base.real_path("memory/note.md"), self.repo / "shared/memory/note.md")
        self.assertEqual(base.real_path("skills"), self.repo / "universal/skills")

    def test_link_map_and_the_base_agree_on_the_view_dirs(self):
        for src, dst, _pattern in overlay_mod.LINK_MAP:
            self.assertEqual(layers_mod.BaseLayer(self.repo).real_path(src), self.repo / dst)

    def test_a_repo_without_layer_json_has_an_empty_base_manifest(self):
        self.assertEqual(layers_mod.BaseLayer(self.repo).manifest(), {})


class BaseInCommandsTests(LayerFixture):
    def test_list_shows_the_base_first(self):
        self.add_overlay("work", 60, {})
        rc, lines = self.run_cmd("list")
        self.assertEqual(rc, 0)
        self.assertTrue(lines[1].startswith("base "), lines)
        self.assertTrue(lines[2].startswith("work "), lines)

    def test_setup_runs_a_base_step(self):
        self.base_steps({"id": "marker", "check": "test -e marker", "run": "touch marker"})
        rc, lines = self.run_cmd("setup", "base", "--only", "marker", "--yes")
        self.assertEqual(rc, 0, lines)
        self.assertTrue((self.repo / "marker").is_file())
        self.assertIn(["OK", "base/marker"], [line.split() for line in lines])

    def test_a_dry_run_lists_base_steps_and_runs_nothing(self):
        self.base_steps({"id": "marker", "check": "test -e marker", "run": "touch marker"})
        rc, lines = self.run_cmd("setup", "--dry-run")
        self.assertEqual(rc, 0)
        self.assertTrue(any(line.startswith("base/marker") and "pending" in line for line in lines), lines)
        self.assertFalse((self.repo / "marker").exists())

    def test_base_steps_come_before_overlay_steps(self):
        self.base_steps({"id": "first", "check": "false", "run": "true"})
        root = self.add_overlay("work", 60, {})
        manifest = json.loads((root / "overlay.json").read_text())
        manifest["setup"] = [{"id": "second", "check": "false", "run": "true"}]
        (root / "overlay.json").write_text(json.dumps(manifest))
        _rc, lines = self.run_cmd("setup", "--dry-run")
        labels = [line.split()[0] for line in lines if "/" in line.split()[0]]
        self.assertEqual(labels, ["base/first", "work/second"])

    def test_status_reports_a_pending_base_step(self):
        self.base_steps({"id": "marker", "check": "test -e marker", "run": "touch marker"})
        rc, lines = self.run_cmd("status")
        self.assertEqual(rc, 1)
        self.assertIn("SETUP base/marker pending — run 'overlay.py setup base'", lines)

    def test_a_base_step_cannot_be_an_agent_step(self):
        self.write("prompt.md", "do something\n")
        self.base_steps({"id": "agent", "check": "false", "agent": "prompt.md"})
        with self.assertRaises(overlay_mod.OverlayError):
            self.run_cmd("setup", "base", "--yes")

    def test_the_alias_base_is_reserved(self):
        with self.assertRaises(overlay_mod.OverlayError):
            self.run_cmd("add", "base", "https://example.invalid/overlay.git")


class ApplyModeTests(LayerFixture):
    def test_an_overlay_without_apply_uses_symlinks(self):
        root = self.add_overlay("work", 60, {"memory/note.md": "note\n"})
        self.assertEqual(overlay_mod.Overlay(alias="work", url="", repo_root=self.repo).apply_mode, "symlink")
        rc, _lines = self.run_cmd("install")
        self.assertEqual(rc, 0)
        link = self.repo / "shared/memory/note.md"
        self.assertTrue(link.is_symlink())
        self.assertEqual(link.resolve(), (root / "memory/note.md").resolve())

    def test_an_unknown_apply_mode_is_refused(self):
        root = self.add_overlay("work", 60, {"memory/note.md": "note\n"})
        manifest = json.loads((root / "overlay.json").read_text())
        manifest["apply"] = "teleport"
        (root / "overlay.json").write_text(json.dumps(manifest))
        with self.assertRaises(overlay_mod.OverlayError) as ctx:
            self.run_cmd("install")
        self.assertIn("unknown apply mode 'teleport'", str(ctx.exception))
        self.assertFalse((self.repo / "shared/memory/note.md").exists())

    def test_an_overlay_file_the_base_already_has_is_still_refused(self):
        self.write("shared/memory/note.md", "base note\n")
        self.add_overlay("work", 60, {"memory/note.md": "overlay note\n"})
        with self.assertRaises(overlay_mod.OverlayError) as ctx:
            self.run_cmd("install")
        self.assertIn("base repo already has it", str(ctx.exception))
        self.assertEqual((self.repo / "shared/memory/note.md").read_text(), "base note\n")


if __name__ == "__main__":
    unittest.main()
