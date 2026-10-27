"""Unit tests for the Codex renders in render_settings.py — stdlib unittest.

Run from repo root:

    python3 scripts/test_render_codex.py
"""

from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import overlay as overlay_mod  # noqa: E402
import render_settings as rs  # noqa: E402

FAKE_HOME = "/home/someone"

LIVE = """\
approvals_reviewer = "auto_review"
model = "picked-in-codex"
service_tier = "fast"
newer_codex_key = 7

[tui]
theme = "tokyonight"

[tui.model_availability_nux]
"gpt-x" = 2

[projects."/somewhere/else"]
trust_level = "trusted"

[mcp_servers.linear]
url = "https://mcp.linear.app/mcp"
"""


def git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@e", *args],
        cwd=cwd, check=True, capture_output=True,
    )


class FixtureRepo(unittest.TestCase):
    """A repo with Codex and MCP bases, and a registry of overlays written by hand."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name) / "repo"
        for sub in ("claude", "codex", "shared/mcp", "shared/instructions", "overlays"):
            (self.repo / sub).mkdir(parents=True)
        self.write("codex/config.base.toml", 'model = "base-model"\napprovals_reviewer = "auto_review"\n')
        self.write(
            "shared/mcp/servers.base.json",
            json.dumps({"servers": {"linear": {"url": "https://mcp.linear.app/mcp", "transport": "http"}}}),
        )
        self.registry: list[dict] = []

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write(self, rel: str, text: str) -> Path:
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def add_overlay(self, alias: str, priority: int, files: dict[str, str]) -> Path:
        root = self.repo / "overlays" / alias
        root.mkdir(parents=True)
        (root / "overlay.json").write_text(json.dumps({"name": alias, "priority": priority}))
        (root / "vars.json").write_text(json.dumps({"CLAUDE_HOME": FAKE_HOME}))
        (root / ".gitignore").write_text("*.local.json\n*.local.toml\n")
        for rel, text in files.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(text)
        git(root, "init", "-q", "-b", "main")
        git(root, "add", "-A")
        git(root, "commit", "-qm", "overlay")
        self.registry.append({"alias": alias, "priority": priority, "enabled": True})
        self.save_registry()
        return root

    def save_registry(self) -> None:
        self.write(overlay_mod.REGISTRY_REL, json.dumps({"overlays": self.registry}))

    def live(self) -> dict:
        return tomllib.loads((self.repo / rs.CODEX_LIVE_REL).read_text())

    def mode(self) -> int:
        return (self.repo / rs.CODEX_LIVE_REL).stat().st_mode & 0o777


class TomlWriterTests(unittest.TestCase):
    def test_round_trip(self):
        data = {
            "top": "a \"quoted\" \\ back\tslash \x7f \x01 emoji 🙂",
            "num": 3,
            "ratio": 0.5,
            "huge": 1e16,
            "infinite": float("inf"),
            "when": datetime.date(2026, 10, 26),
            "flags": [True, False],
            "mixed": [1, "two", {"three": 3}],
            "empty_list": [],
            "inline_in_array": [[1, 2], [3]],
            "projects": {"/a.b/c d": {"trust_level": "trusted"}, "": {"x": 1}},
            "empty": {},
            "only_subtables": {"inner": {"leaf": 1}},
            "hooks": [{"name": "one", "env": {"K": "v"}, "steps": [{"run": "a"}, {"run": "b"}]}, {"name": "two"}],
        }
        text = rs.dumps_toml(data, "a comment\nsecond line")
        self.assertEqual(tomllib.loads(text), data)
        self.assertTrue(text.startswith("# a comment\n# second line\n"))
        self.assertEqual(text, rs.dumps_toml(data, "a comment\nsecond line"))

    def test_null_has_no_toml_form(self):
        with self.assertRaises(ValueError):
            rs.dumps_toml({"a": {"b": None}})


class CodexMcpTests(unittest.TestCase):
    def test_mapping(self):
        servers = {"servers": {
            "remote": {"url": "https://x", "headers": {"Auth": "t"}},
            "local": {"command": "kb", "args": ["--port", 7], "env": {"N": 1}, "enabled": False},
            "streaming": {"url": "https://y", "transport": "sse"},
            "broken": {"description": "nothing to run"},
        }}
        out = rs.codex_mcp_servers(servers)
        self.assertEqual(out["remote"], {"url": "https://x", "http_headers": {"Auth": "t"}})
        self.assertEqual(out["local"], {"command": "kb", "args": ["--port", "7"], "env": {"N": "1"}, "enabled": False})
        self.assertNotIn("streaming", out)
        self.assertNotIn("broken", out)


class RenderCodexTests(FixtureRepo):
    def test_first_render_keeps_everything_codex_wrote(self):
        self.write(rs.CODEX_LIVE_REL, LIVE).chmod(0o664)
        rs.render_codex(self.repo)
        live = self.live()
        self.assertEqual(live["projects"], {"/somewhere/else": {"trust_level": "trusted"}})
        self.assertEqual(live["tui"]["model_availability_nux"], {"gpt-x": 2})
        self.assertEqual(live["newer_codex_key"], 7)
        self.assertEqual(live["service_tier"], "fast")
        self.assertEqual(self.mode(), 0o600)

    def test_base_keys_are_pinned(self):
        self.write(rs.CODEX_LIVE_REL, LIVE)
        rs.render_codex(self.repo)
        self.assertEqual(self.live()["model"], "base-model")

    def test_new_file_is_private(self):
        rs.render_codex(self.repo)
        self.assertEqual(self.mode(), 0o600)
        self.assertEqual(self.live()["mcp_servers"]["linear"]["url"], "https://mcp.linear.app/mcp")

    def test_a_key_removed_from_the_base_is_dropped_and_runtime_keys_stay(self):
        self.write(rs.CODEX_LIVE_REL, LIVE)
        rs.render_codex(self.repo)
        self.write("codex/config.base.toml", 'model = "base-model"\n')
        rs.render_codex(self.repo)
        live = self.live()
        self.assertNotIn("approvals_reviewer", live)
        self.assertEqual(live["newer_codex_key"], 7)

    def test_overlay_fragments_and_their_removal(self):
        self.add_overlay("work", 60, {
            "settings/codex.toml": '[projects."${CLAUDE_HOME}/work"]\ntrust_level = "trusted"\n',
            "mcp/servers.json": json.dumps({"servers": {"kb": {"command": "/opt/kb"}}}),
        })
        rs.render_codex(self.repo)
        live = self.live()
        self.assertIn(f"{FAKE_HOME}/work", live["projects"])
        self.assertEqual(live["mcp_servers"]["kb"], {"command": "/opt/kb"})

        self.registry.clear()
        self.save_registry()
        rs.render_codex(self.repo)
        live = self.live()
        self.assertNotIn("projects", live)
        self.assertNotIn("kb", live["mcp_servers"])

    def test_local_fragment_beats_its_own_overlay(self):
        root = self.add_overlay("personal", 50, {"settings/codex.toml": 'model = "shared"\n'})
        (root / "settings" / "codex.local.toml").write_text('model = "this-machine"\n')
        rs.render_codex(self.repo)
        self.assertEqual(self.live()["model"], "this-machine")

    def test_base_refuses_local_only_keys(self):
        self.write("codex/config.base.toml", '[projects."/x"]\ntrust_level = "trusted"\n')
        with self.assertRaises(ValueError):
            rs.render_codex(self.repo)

    def test_an_unparsable_live_file_is_left_alone(self):
        path = self.write(rs.CODEX_LIVE_REL, "model = \n")
        with self.assertRaises(ValueError):
            rs.render_codex(self.repo)
        self.assertEqual(path.read_text(), "model = \n")

    def test_a_tracked_target_is_refused(self):
        self.write(rs.CODEX_LIVE_REL, LIVE)
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "add", rs.CODEX_LIVE_REL)
        git(self.repo, "commit", "-qm", "tracked")
        with self.assertRaises(ValueError):
            rs.render_codex(self.repo)
        self.assertEqual((self.repo / rs.CODEX_LIVE_REL).read_text(), LIVE)

    def test_a_current_file_is_not_rewritten_even_when_reformatted(self):
        rs.render_codex(self.repo)
        path = self.repo / rs.CODEX_LIVE_REL
        # Codex rewrites with its own formatting; same data is not drift.
        data = self.live()
        path.write_text(rs.dumps_toml(dict(reversed(list(data.items())))))
        before = path.stat().st_mtime_ns
        merged = rs.render_codex(self.repo)
        self.assertTrue(rs.artifact_current(self.repo, rs.CODEX_LIVE_REL, merged))
        self.assertEqual(path.stat().st_mtime_ns, before)

    def test_status_flags_an_unignored_local_toml(self):
        root = self.add_overlay("personal", 50, {})
        (root / ".gitignore").write_text("*.local.json\n")
        (root / "settings").mkdir()
        (root / "settings" / "codex.local.toml").write_text('model = "x"\n')
        lines: list[str] = []
        overlay_mod.cmd_status(self.repo, None, lines.append)
        self.assertTrue(any(line.startswith("LOCAL personal/settings/codex.local.toml") for line in lines), lines)


class CodexAgentsTests(FixtureRepo):
    def setUp(self) -> None:
        super().setUp()
        self.write("shared/AGENTS.md", (
            "# Agent Instructions\n\n"
            "## Language\n\nSee [instructions/language.md](./instructions/language.md).\n\n"
            "## Personal context\n\nSee [instructions/personal.md](./instructions/personal.md) — from an overlay. "
            "See [docs/overlay.md](../docs/overlay.md).\n\n"
            "## Long-term memory\n\nLives in [memory/MEMORY.md](./memory/MEMORY.md).\n"
        ))
        self.write("shared/instructions/language.md", (
            "# Language\n\n- Reply in Korean.\n\n## Detail\n\nSee [git](./git-workflow.md).\n\n"
            "```sh\n# a shell comment, not a heading\n```\n"
        ))

    def test_links_are_inlined_and_made_absolute(self):
        text = rs.render_codex_agents(self.repo)
        shared = os.path.abspath(self.repo / "shared")
        self.assertIn("- Reply in Korean.", text)
        self.assertNotIn("# Language\n", text.replace("## Language", ""))
        self.assertIn("### Detail", text)
        self.assertIn(f"]({shared}/instructions/git-workflow.md)", text)
        self.assertIn(f"]({shared}/memory/MEMORY.md)", text)
        self.assertIn("# a shell comment, not a heading", text)
        self.assertNotIn("## a shell comment", text)
        # personal.md is absent without an overlay, so its line goes.
        self.assertNotIn("instructions/personal.md", text)
        self.assertEqual((self.repo / rs.CODEX_AGENTS_REL).read_text(), text)


if __name__ == "__main__":
    unittest.main()
