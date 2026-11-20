"""Unit tests for layers.py and the base layer in overlay.py — stdlib unittest.

Run from repo root:

    python3 scripts/test_layers.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
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


class CheckoutFixture(LayerFixture):
    """Overlays whose origin repo uses the checkout layout (paths relative to the harness root)."""

    def setUp(self) -> None:
        super().setUp()
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "fixture base")

    def base_status_views(self) -> list[str]:
        """Paths under the view dirs that the base's git status shows at all."""
        out = self.git_out(self.repo, "status", "--porcelain", "--untracked-files=all")
        views = tuple(dst + "/" for dst in layers_mod.VIEW_DIRS.values())
        # The rendered index is gitignored in the real repo; this fixture has no .gitignore.
        return [line[3:] for line in out.splitlines() if line[3:].startswith(views) and line[3:] != rs.MEMORY_LIVE_REL]

    def origin(self, name: str, files: dict[str, str]) -> Path:
        root = Path(self._tmp.name) / f"{name}-origin"
        root.mkdir()
        git(root, "init", "-q", "-b", "main")
        for rel, text in files.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(text)
        git(root, "add", "-A")
        git(root, "commit", "-qm", "overlay")
        return root

    def checkout_files(self, alias: str, extra: dict[str, str]) -> dict[str, str]:
        own = f"overlays/{alias}/"
        return {own + "overlay.json": json.dumps({"name": alias, "priority": 60}), own + ".gitignore": "*.local.json\n", **extra}

    def add_checkout(self, alias: str, extra: dict[str, str]) -> Path:
        origin = self.origin(alias, self.checkout_files(alias, extra))
        rc, _lines = self.run_cmd("add", alias, str(origin))
        self.assertEqual(rc, 0)
        self.sync_fixture_registry()
        return origin

    def sync_fixture_registry(self) -> None:
        self.registry = json.loads((self.repo / overlay_mod.REGISTRY_REL).read_text())["overlays"]

    def overlay(self, alias: str) -> overlay_mod.Overlay:
        return overlay_mod.Overlay(alias=alias, url="", repo_root=self.repo)

    def git_out(self, cwd: Path, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout

    def applied(self) -> dict[str, dict]:
        return {item["link"]: item for item in overlay_mod.load_applied(self.repo)}

    def commit_in_base(self, files: dict[str, str]) -> None:
        for rel, text in files.items():
            self.write(rel, text)
        git(self.repo, "add", *files)
        git(self.repo, "commit", "-qm", "base")


NOTE = {"shared/memory/note.md": "needle note\n", "universal/skills/tool/SKILL.md": "---\nname: tool\n---\n"}


class CheckoutModeTests(CheckoutFixture):
    def test_add_checks_the_view_files_out_in_place(self):
        self.add_checkout("work", NOTE)
        note = self.repo / "shared/memory/note.md"
        self.assertTrue(note.is_file() and not note.is_symlink())
        self.assertEqual(note.read_text(), "needle note\n")
        self.assertTrue((self.repo / "universal/skills/tool").is_dir())
        self.assertTrue(overlay_mod.is_checkout_clone(self.overlay("work")))
        self.assertEqual(self.overlay("work").apply_mode, "checkout")
        self.assertTrue(overlay_mod.hooks_current(self.overlay("work")))

    def test_install_records_the_files_and_hides_them_from_the_base(self):
        self.add_checkout("work", NOTE)
        rc, lines = self.run_cmd("install")
        self.assertEqual(rc, 0, lines)
        applied = self.applied()
        self.assertEqual(applied["shared/memory/note.md"]["mode"], "checkout")
        self.assertEqual(applied["universal/skills/tool"]["mode"], "checkout")
        self.assertEqual(self.base_status_views(), [])
        ignore = (self.repo / ".ignore").read_text()
        self.assertIn("!/shared/memory/note.md", ignore)
        self.assertIn("!/universal/skills/tool/", ignore)
        self.assertIn("/.ignore", (self.repo / ".git/info/exclude").read_text())

    def test_an_edit_shows_in_the_overlay_and_not_in_the_base(self):
        self.add_checkout("work", NOTE)
        self.run_cmd("install")
        (self.repo / "shared/memory/note.md").write_text("changed\n")
        self.assertIn("shared/memory/note.md", self.git_out(self.repo / "overlays/work", "status", "--porcelain"))
        self.assertEqual(self.base_status_views(), [])
        rc, lines = self.run_cmd("status")
        self.assertIn(f"DIRTY work has uncommitted changes in {self.repo / 'overlays/work'}", lines)

    def test_a_path_the_base_tracks_is_refused_and_left_alone(self):
        self.commit_in_base({"shared/memory/note.md": "base note\n"})
        origin = self.origin("work", self.checkout_files("work", NOTE))
        with self.assertRaises(overlay_mod.OverlayError):
            self.run_cmd("add", "work", str(origin))
        self.assertEqual((self.repo / "shared/memory/note.md").read_text(), "base note\n")
        self.assertFalse((self.repo / "overlays/work").exists())

    def try_commit(self, clone: Path, path: str) -> subprocess.CompletedProcess:
        git(clone, "add", "-f", path)
        result = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@e", "commit", "-qm", "x"],
                                cwd=clone, capture_output=True, text=True)
        git(clone, "reset", "-q")
        return result

    def test_the_guard_refuses_a_base_file_and_takes_a_view_file(self):
        self.commit_in_base({"README.md": "base readme\n", "shared/memory/base.md": "base memory\n"})
        self.add_checkout("work", NOTE)
        clone = self.repo / "overlays/work"
        outside = self.try_commit(clone, "../../README.md")
        self.assertNotEqual(outside.returncode, 0)
        self.assertIn("outside overlay 'work'", outside.stderr)
        tracked = self.try_commit(clone, "../../shared/memory/base.md")
        self.assertNotEqual(tracked.returncode, 0)
        self.assertIn("tracked by the harness repo", tracked.stderr)
        self.write("shared/memory/new.md", "new\n")
        git(clone, "add", "../../shared/memory/new.md")
        git(clone, "commit", "-qm", "new memory")
        self.assertIn("shared/memory/new.md", self.git_out(clone, "ls-files", "--full-name", ":/"))

    def test_sync_views_picks_up_a_newly_committed_view_file(self):
        self.add_checkout("work", NOTE)
        self.run_cmd("install")
        clone = self.repo / "overlays/work"
        self.write("shared/memory/new.md", "new\n")
        git(clone, "add", "../../shared/memory/new.md")
        git(clone, "commit", "-qm", "new memory")
        rc, _lines = self.run_cmd("sync-views")
        self.assertEqual(rc, 0)
        self.assertEqual(self.applied()["shared/memory/new.md"]["mode"], "checkout")
        self.assertEqual(self.base_status_views(), [])

    def test_a_symlink_overlay_cannot_take_a_checked_out_file(self):
        self.add_checkout("work", NOTE)
        self.run_cmd("install")
        self.add_overlay("zz", 70, {"memory/note.md": "other\n"})
        with self.assertRaises(overlay_mod.OverlayError) as ctx:
            self.run_cmd("install")
        self.assertIn("keeps its own file there", str(ctx.exception))
        self.assertEqual((self.repo / "shared/memory/note.md").read_text(), "needle note\n")

    def test_remove_needs_purge_and_a_clean_pushed_clone(self):
        self.add_checkout("work", NOTE)
        self.run_cmd("install")
        with self.assertRaises(overlay_mod.OverlayError):
            self.run_cmd("remove", "work")
        (self.repo / "shared/memory/note.md").write_text("unsaved\n")
        with self.assertRaises(overlay_mod.OverlayError):
            self.run_cmd("remove", "work", "--purge")
        (self.repo / "shared/memory/note.md").write_text("needle note\n")
        rc, _lines = self.run_cmd("remove", "work", "--purge")
        self.assertEqual(rc, 0)
        self.assertFalse((self.repo / "shared/memory/note.md").exists())
        self.assertFalse((self.repo / "universal/skills/tool").exists())
        self.assertFalse((self.repo / "overlays/work").exists())

    @unittest.skipUnless(shutil.which("rg"), "rg not installed")
    def test_rg_finds_a_checked_out_file(self):
        self.add_checkout("work", NOTE)
        self.run_cmd("install")
        found = subprocess.run(["rg", "-l", "needle", "shared"], cwd=self.repo, capture_output=True, text=True).stdout
        self.assertIn("shared/memory/note.md", found)


class FilingTests(CheckoutFixture):
    """UNFILED in status, `overlay.py file`, and the base's commit guard."""

    def setUp(self) -> None:
        super().setUp()
        self.write("shared/memory/MEMORY.base.md", "- [Base](base.md) — a base memory\n")
        git(self.repo, "add", "shared/memory/MEMORY.base.md")
        git(self.repo, "commit", "-qm", "index")

    def new_memory(self, name: str) -> None:
        """A memory written straight into the view dir, its line appended to the rendered index."""
        self.write(f"shared/memory/{name}", f"---\nname: {name}\n---\nx\n")
        live = self.repo / rs.MEMORY_LIVE_REL
        live.write_text((live.read_text() if live.is_file() else "") + f"- [New]({name}) — new\n")

    def staged(self, cwd: Path) -> list[str]:
        return self.git_out(cwd, "diff", "--cached", "--name-only").split()

    def test_status_lists_an_unfiled_memory_and_file_to_base_stages_it(self):
        self.run_cmd("install")
        self.new_memory("loose.md")
        _rc, lines = self.run_cmd("status")
        self.assertTrue(any(line.startswith("UNFILED shared/memory/loose.md") for line in lines), lines)
        rc, lines = self.run_cmd("file", str(self.repo / "shared/memory/loose.md"), "--to", "base")
        self.assertEqual(rc, 0, lines)
        self.assertIn("shared/memory/loose.md", self.staged(self.repo))
        self.assertIn("- [New](loose.md) — new", (self.repo / "shared/memory/MEMORY.base.md").read_text())
        _rc, lines = self.run_cmd("status")
        self.assertFalse(any(line.startswith("UNFILED") for line in lines), lines)

    def test_file_to_a_checkout_overlay_stages_it_there_and_hides_it_from_the_base(self):
        self.add_checkout("work", NOTE)
        self.run_cmd("install")
        self.new_memory("work_note.md")
        rc, lines = self.run_cmd("file", str(self.repo / "shared/memory/work_note.md"), "--to", "work")
        self.assertEqual(rc, 0, lines)
        self.assertIn("shared/memory/work_note.md", self.staged(self.repo / "overlays/work"))
        self.assertNotIn("shared/memory/work_note.md", self.staged(self.repo))
        self.assertEqual(self.base_status_views(), [])
        self.assertIn("- [New](work_note.md) — new", (self.repo / "overlays/work/memory/MEMORY.md").read_text())
        self.assertNotIn("work_note.md", (self.repo / "shared/memory/MEMORY.base.md").read_text())

    def test_file_to_a_symlink_overlay_moves_it_in_and_links_it_back(self):
        self.add_overlay("sym", 70, {"memory/old.md": "old\n"})
        self.run_cmd("install")
        self.new_memory("sym_note.md")
        rc, lines = self.run_cmd("file", str(self.repo / "shared/memory/sym_note.md"), "--to", "sym")
        self.assertEqual(rc, 0, lines)
        self.assertTrue((self.repo / "overlays/sym/memory/sym_note.md").is_file())
        self.assertTrue((self.repo / "shared/memory/sym_note.md").is_symlink())
        self.assertIn("memory/sym_note.md", self.staged(self.repo / "overlays/sym"))

    def test_filing_something_already_tracked_is_refused(self):
        self.add_checkout("work", NOTE)
        self.run_cmd("install")
        with self.assertRaises(overlay_mod.OverlayError):
            self.run_cmd("file", str(self.repo / "shared/memory/note.md"), "--to", "base")

    def test_the_base_guard_refuses_a_file_an_overlay_provides(self):
        self.add_checkout("work", NOTE)
        self.run_cmd("install")
        self.assertIn(overlay_mod.HOOK_MARKER, (self.repo / ".git/hooks/pre-commit").read_text())
        git(self.repo, "add", "-f", "shared/memory/note.md")
        rc, _lines = self.run_cmd("check-staged")
        self.assertEqual(rc, 1)
        git(self.repo, "reset", "-q")
        self.new_memory("fine.md")
        git(self.repo, "add", "shared/memory/fine.md")
        rc, _lines = self.run_cmd("check-staged")
        self.assertEqual(rc, 0)


class ConvertTests(CheckoutFixture):
    LEGACY = {
        "overlay.json": json.dumps({"name": "work", "priority": 60}),
        "README.md": "overlay readme\n",
        ".gitignore": "*.local.json\n",
        "feedback/a.json": "{}\n",
        "memory/note.md": "needle note\n",
        "memory/MEMORY.md": "- [Note](note.md) — a note\n",
        "skills/tool/SKILL.md": "---\nname: tool\n---\n",
    }

    def legacy(self) -> Path:
        origin = self.origin("work", self.LEGACY)
        rc, _lines = self.run_cmd("add", "work", str(origin))
        self.assertEqual(rc, 0)
        self.sync_fixture_registry()
        self.run_cmd("install")
        self.assertTrue((self.repo / "shared/memory/note.md").is_symlink())
        return origin

    def restructure(self, origin: Path, extra_change: bool = False) -> None:
        (origin / "overlays/work").mkdir(parents=True)
        for name in ("overlay.json", "README.md", ".gitignore", "feedback"):
            git(origin, "mv", name, f"overlays/work/{name}")
        (origin / "overlays/work/memory").mkdir()
        git(origin, "mv", "memory/MEMORY.md", "overlays/work/memory/MEMORY.md")
        (origin / "shared/memory").mkdir(parents=True)
        git(origin, "mv", "memory/note.md", "shared/memory/note.md")
        (origin / "universal/skills").mkdir(parents=True)
        git(origin, "mv", "skills/tool", "universal/skills/tool")
        if extra_change:
            (origin / "overlays/work/README.md").write_text("edited too\n")
            git(origin, "add", "-A")
        git(origin, "commit", "-qm", "restructure")

    def test_convert_moves_view_files_into_place_and_never_touches_the_base(self):
        self.commit_in_base({"README.md": "base readme\n", ".gitignore": "overlays/\n"})
        origin = self.legacy()
        self.restructure(origin)
        (self.repo / "overlays/work/feedback/a.json").unlink()  # a local deletion must survive
        rc, lines = self.run_cmd("convert", "work")
        self.assertEqual(rc, 0, lines)
        self.assertEqual((self.repo / "README.md").read_text(), "base readme\n")
        self.assertEqual((self.repo / ".gitignore").read_text(), "overlays/\n")
        note = self.repo / "shared/memory/note.md"
        self.assertTrue(note.is_file() and not note.is_symlink())
        skill = self.repo / "universal/skills/tool"
        self.assertTrue(skill.is_dir() and not skill.is_symlink())
        self.assertFalse((self.repo / "overlays/work/memory/note.md").exists())
        self.assertFalse((self.repo / "overlays/work/feedback/a.json").exists())
        self.assertTrue(overlay_mod.is_checkout_clone(self.overlay("work")))
        status = self.git_out(self.repo / "overlays/work", "status", "--porcelain")
        self.assertEqual(status.split(), ["D", "overlays/work/feedback/a.json"])  # porcelain paths are root-relative
        self.assertEqual(self.base_status_views(), [])
        self.assertEqual(self.applied()["shared/memory/note.md"]["mode"], "checkout")
        self.assertTrue((self.repo / "overlays/work/memory/MEMORY.md").is_file())  # the index fragment stays the overlay's own

    def test_a_dry_run_changes_nothing(self):
        origin = self.legacy()
        self.restructure(origin)
        rc, lines = self.run_cmd("convert", "work", "--dry-run")
        self.assertEqual(rc, 0)
        self.assertIn("MOVE  overlays/work/memory/note.md -> shared/memory/note.md", lines)
        self.assertTrue((self.repo / "shared/memory/note.md").is_symlink())
        self.assertFalse(overlay_mod.is_checkout_clone(self.overlay("work")))

    def test_a_restructure_that_also_edits_is_refused(self):
        origin = self.legacy()
        self.restructure(origin, extra_change=True)
        with self.assertRaises(overlay_mod.OverlayError) as ctx:
            self.run_cmd("convert", "work")
        self.assertIn("must only move files", str(ctx.exception))
        self.assertTrue((self.repo / "shared/memory/note.md").is_symlink())
        self.assertFalse(overlay_mod.is_checkout_clone(self.overlay("work")))

    def test_an_untracked_linked_file_blocks_the_convert(self):
        origin = self.legacy()
        self.restructure(origin)
        (self.repo / "overlays/work/memory/draft.md").write_text("work in progress\n")
        self.run_cmd("install")
        self.assertTrue((self.repo / "shared/memory/draft.md").is_symlink())
        with self.assertRaises(overlay_mod.OverlayError) as ctx:
            self.run_cmd("convert", "work")
        self.assertIn("shared/memory/draft.md", str(ctx.exception))
        self.assertTrue((self.repo / "shared/memory/draft.md").is_symlink())
        self.assertFalse(overlay_mod.is_checkout_clone(self.overlay("work")))

    def test_update_stops_before_pulling_a_restructure_into_a_symlink_clone(self):
        origin = self.legacy()
        self.restructure(origin)
        rc, lines = self.run_cmd("update", "work")
        self.assertEqual(rc, 0)
        self.assertIn("STOP  work: upstream moved to the checkout layout — run 'overlay.py convert work'", lines)
        self.assertTrue((self.repo / "overlays/work/overlay.json").is_file())
        self.assertTrue((self.repo / "shared/memory/note.md").is_symlink())


if __name__ == "__main__":
    unittest.main()
