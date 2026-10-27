"""Unit tests for render_settings.py — stdlib unittest.

Mostly the Codex renders, plus what they share with the other artifacts: the
live-state merge, the data comparison, keeping MCP credentials private, and
the all-or-nothing render.

Run from repo root:

    python3 scripts/test_render_codex.py
"""

from __future__ import annotations

import contextlib
import datetime
import io
import json
import math
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import overlay as overlay_mod  # noqa: E402
import render_settings as rs  # noqa: E402

# Whatever reader render_settings found: tomllib, or tomli before 3.11.
tomllib = rs.tomllib
needs_toml = unittest.skipIf(tomllib is None, rs.NO_TOML_READER)

FAKE_HOME = "/home/someone"
REPO_ROOT = Path(__file__).resolve().parent.parent

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

    def edit_live(self, change) -> None:
        data = self.live()
        change(data)
        (self.repo / rs.CODEX_LIVE_REL).write_text(rs.dumps_toml(data))

    def mode(self) -> int:
        return (self.repo / rs.CODEX_LIVE_REL).stat().st_mode & 0o777


@needs_toml
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

    def test_nan_passes_the_read_back_check(self):
        text = rs.dumps_toml({"x": float("nan"), "t": {"y": [float("nan"), 1]}})
        self.assertTrue(math.isnan(tomllib.loads(text)["x"]))


class SameDataTests(unittest.TestCase):
    def test_booleans_are_not_numbers(self):
        for numbers_by_value in (False, True):
            self.assertFalse(rs.same_data(True, 1, numbers_by_value))
            self.assertFalse(rs.same_data({"a": [False]}, {"a": [0]}, numbers_by_value))
            self.assertFalse(rs.same_data(0.0, False, numbers_by_value))

    def test_integers_and_floats_differ_unless_compared_by_value(self):
        self.assertFalse(rs.same_data({"n": 1}, {"n": 1.0}))
        self.assertTrue(rs.same_data({"n": 1}, {"n": 1.0}, numbers_by_value=True))
        self.assertFalse(rs.same_data(1, 2.0, numbers_by_value=True))

    def test_nan_equals_itself(self):
        self.assertTrue(rs.same_data({"a": [float("nan")]}, {"a": [float("nan")]}))
        self.assertTrue(rs.same_data(float("nan"), float("nan"), numbers_by_value=True))
        self.assertFalse(rs.same_data(float("nan"), 1.0))

    def test_key_order_is_ignored_and_list_order_is_not(self):
        self.assertTrue(rs.same_data({"a": 1, "b": 2}, {"b": 2, "a": 1}))
        self.assertFalse(rs.same_data([1, 2], [2, 1]))
        self.assertFalse(rs.same_data({"a": 1}, {"a": 1, "b": 2}))
        self.assertFalse(rs.same_data([1], [1, 1]))


class DeepMergeTests(unittest.TestCase):
    def test_json_sources_append_with_a_plus_key(self):
        merged = rs.deep_merge({"hooks": {"Stop": [1]}}, {"hooks": {"Stop+": [2], "New+": [3]}})
        self.assertEqual(merged, {"hooks": {"Stop": [1, 2], "New": [3]}})

    def test_without_markers_every_key_is_literal(self):
        base = {"projects": {"/src/c": {"trust_level": "trusted"}}}
        patch = {"projects": {"/src/c++": {"trust_level": "trusted"}, "/src/c": {"x": 1}}}
        merged = rs.deep_merge(base, patch, markers=False)
        self.assertEqual(merged["projects"], {
            "/src/c": {"trust_level": "trusted", "x": 1},
            "/src/c++": {"trust_level": "trusted"},
        })


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

    def mapped(self, servers: dict) -> tuple[dict, str]:
        if tomllib is None:
            self.skipTest(rs.NO_TOML_READER)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            out = rs.codex_mcp_servers({"servers": servers})
        # Whatever the mapping produces has to survive the TOML writer.
        self.assertEqual(tomllib.loads(rs.dumps_toml({"mcp_servers": out})), {"mcp_servers": out})
        return out, err.getvalue()

    def test_env_references_are_forwarded_not_copied(self):
        out, err = self.mapped({
            "kb": {"command": "kb", "env": {"API_TOKEN": "${API_TOKEN}", "MODE": "ro"}},
            "only": {"command": "kb", "env": {"A": "${A}", "B": "${B}"}},
        })
        self.assertEqual(out["kb"], {"command": "kb", "env": {"MODE": "ro"}, "env_vars": ["API_TOKEN"]})
        self.assertEqual(out["only"], {"command": "kb", "env_vars": ["A", "B"]})
        self.assertEqual(err, "")

    def test_header_references_use_codex_env_fields(self):
        out, err = self.mapped({"wiki": {"url": "https://w", "headers": {
            "Authorization": "Bearer ${WIKI_TOKEN}",
            "X-Api-Key": "${WIKI_KEY}",
            "X-Team": "static",
        }}})
        self.assertEqual(out["wiki"], {
            "url": "https://w",
            "bearer_token_env_var": "WIKI_TOKEN",
            "env_http_headers": {"X-Api-Key": "WIKI_KEY"},
            "http_headers": {"X-Team": "static"},
        })
        self.assertEqual(err, "")

    def test_a_whole_authorization_value_is_a_plain_env_header(self):
        out, _ = self.mapped({"w": {"url": "https://w", "headers": {"authorization": "${AUTH}"}}})
        self.assertEqual(out["w"], {"url": "https://w", "env_http_headers": {"authorization": "AUTH"}})

    def test_references_codex_cannot_take_stay_literal_with_a_warning(self):
        out, err = self.mapped({
            "kb": {"command": "${KB_BIN}", "args": ["--db", "${DB}"], "env": {
                "GITHUB_TOKEN": "${GH_PAT}",          # env_vars cannot rename
                "DSN": "pg://u:${DB_PASS}@host/x",   # part of a longer value
                "LEVEL": "${LEVEL:-info}",           # a default is Claude Code syntax
            }},
            "wiki": {"url": "https://${HOST}/mcp", "headers": {"Authorization": "Token ${T}"}},
        })
        self.assertEqual(out["kb"]["env"], {
            "GITHUB_TOKEN": "${GH_PAT}", "DSN": "pg://u:${DB_PASS}@host/x", "LEVEL": "${LEVEL:-info}",
        })
        self.assertNotIn("env_vars", out["kb"])
        self.assertEqual(out["wiki"]["http_headers"], {"Authorization": "Token ${T}"})
        self.assertNotIn("bearer_token_env_var", out["wiki"])
        for where in ("'kb' command line", "'kb' env GITHUB_TOKEN", "'kb' env DSN", "'kb' env LEVEL",
                      "'wiki' url", "'wiki' header Authorization"):
            self.assertIn(f"MCP server {where} has a ${{...}}", err)
        # A warning names the field, never the value around the reference.
        self.assertNotIn("pg://", err)


class PreserveUnmanagedTests(unittest.TestCase):
    def test_a_dropped_table_keeps_what_the_tool_added(self):
        live = {"enabledPlugins": {"from-overlay@m": True, "installed@m": True}, "model": "x"}
        dropped = frozenset({("enabledPlugins",), ("enabledPlugins", "from-overlay@m")})
        out = rs.preserve_unmanaged(live, {"model": "x"}, dropped)
        self.assertEqual(out["enabledPlugins"], {"installed@m": True})

    def test_a_dropped_table_with_nothing_else_in_it_goes(self):
        live = {"env": {"A": "1", "B": {"nested": "2"}}}
        dropped = frozenset({("env",), ("env", "A"), ("env", "B"), ("env", "B", "nested")})
        self.assertEqual(rs.preserve_unmanaged(live, {}, dropped), {})

    def test_an_atomic_table_goes_whole(self):
        status = {"statusLine": {"type": "command", "command": "x", "refreshInterval": 5}}
        dropped = frozenset({("statusLine",), ("statusLine", "type"), ("statusLine", "command")})
        self.assertEqual(rs.preserve_unmanaged(status, {}, dropped, atomic=rs.CLAUDE_ATOMIC), {})

        server = {"command": "kb", "enabled": False, "tools": {"t": {"approval_mode": "approve"}}}
        dropped = frozenset({("mcp_servers",), ("mcp_servers", "kb"), ("mcp_servers", "kb", "command")})
        out = rs.preserve_unmanaged({"mcp_servers": {"kb": server}}, {}, dropped, atomic=rs.CODEX_ATOMIC)
        self.assertEqual(out, {})


@needs_toml
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

    def test_a_live_stdio_table_loses_its_transport_to_the_sources_url(self):
        # What `codex mcp add linear -- npx -y mcp-remote ...` leaves behind, or a
        # pre-harness config install.py seeds; url next to command is an error
        # that makes Codex reject the whole file.
        self.write(rs.CODEX_LIVE_REL, (
            '[mcp_servers.linear]\ncommand = "npx"\nargs = ["-y", "mcp-remote"]\n'
            'env = { A = "b" }\nenv_vars = ["A"]\ncwd = "/tmp"\n'
            'startup_timeout_sec = 60\nenabled_tools = ["list_issues"]\n'
        ))
        rs.render_codex(self.repo)
        self.assertEqual(self.live()["mcp_servers"]["linear"], {
            "url": "https://mcp.linear.app/mcp",
            "startup_timeout_sec": 60,
            "enabled_tools": ["list_issues"],
        })

    def test_a_live_url_table_loses_its_transport_to_the_sources_command(self):
        self.add_overlay("work", 60, {
            "mcp/servers.json": json.dumps({"servers": {"kb": {"command": "/opt/kb"}}}),
        })
        self.write(rs.CODEX_LIVE_REL, (
            '[mcp_servers.kb]\nurl = "https://kb"\nbearer_token_env_var = "T"\noauth_resource = "https://kb"\n'
            'tool_timeout_sec = 90\nhttp_headers = { A = "b" }\nenv_http_headers = { A = "B" }\n'
            'http_headers_helper = "/bin/h"\nauth = "oauth"\n'
            # What `codex mcp add kb --url ... --oauth-client-id C` writes.
            '[mcp_servers.kb.oauth]\nclient_id = "C"\ncallback_url = "http://127.0.0.1:1/cb"\n'
        ))
        rs.render_codex(self.repo)
        self.assertEqual(self.live()["mcp_servers"]["kb"], {"command": "/opt/kb", "tool_timeout_sec": 90})

    def test_live_keys_of_the_same_transport_and_live_only_servers_stay(self):
        self.add_overlay("work", 60, {
            # A fragment that only tunes a server names no transport of its own.
            "settings/codex.toml": "[mcp_servers.hand]\nenabled = false\n",
        })
        self.write(rs.CODEX_LIVE_REL, (
            '[mcp_servers.linear]\nurl = "https://mcp.linear.app/mcp"\nbearer_token_env_var = "T"\n'
            '[mcp_servers.hand]\nurl = "https://hand"\n'
            '[mcp_servers.mine]\ncommand = "mine"\nargs = ["x"]\n'
        ))
        rs.render_codex(self.repo)
        servers = self.live()["mcp_servers"]
        self.assertEqual(servers["linear"], {"url": "https://mcp.linear.app/mcp", "bearer_token_env_var": "T"})
        self.assertEqual(servers["hand"], {"url": "https://hand", "enabled": False})
        self.assertEqual(servers["mine"], {"command": "mine", "args": ["x"]})

    def test_what_codex_added_outlives_the_overlay_that_brought_the_table(self):
        self.add_overlay("work", 60, {
            "settings/codex.toml": '[projects."${CLAUDE_HOME}/work"]\ntrust_level = "trusted"\n',
            "mcp/servers.json": json.dumps({"servers": {"kb": {"command": "/opt/kb"}}}),
        })
        rs.render_codex(self.repo)

        def codex_writes(data):
            # What Codex 0.163 writes: a directory trusted at its prompt, an
            # overlay server switched off with one tool approved for good, and
            # a server of the user's own from `codex mcp add`.
            data["projects"]["/somewhere/else"] = {"trust_level": "trusted"}
            data["mcp_servers"]["kb"]["enabled"] = False
            data["mcp_servers"]["kb"]["tools"] = {"search": {"approval_mode": "approve"}}
            data["mcp_servers"]["mine"] = {"command": "/usr/bin/mine"}

        self.edit_live(codex_writes)
        self.registry.clear()
        self.save_registry()
        rs.render_codex(self.repo)
        live = self.live()
        self.assertEqual(live["projects"], {"/somewhere/else": {"trust_level": "trusted"}})
        # Not a transport-less {enabled, tools} stub, which Codex would refuse.
        self.assertNotIn("kb", live["mcp_servers"])
        self.assertEqual(live["mcp_servers"]["mine"], {"command": "/usr/bin/mine"})

    def test_an_otel_exporter_goes_whole(self):
        # Codex refuses an exporter without its endpoint ("missing field `endpoint`").
        self.add_overlay("work", 60, {
            "settings/codex.toml": '[otel.exporter.otlp-http]\nendpoint = "https://o"\nprotocol = "binary"\n',
        })
        rs.render_codex(self.repo)
        self.edit_live(lambda data: data["otel"]["exporter"]["otlp-http"].update(headers={"x": "y"}))
        self.registry.clear()
        self.save_registry()
        rs.render_codex(self.repo)
        self.assertNotIn("otel", self.live())

    def test_a_server_codex_added_outlives_the_last_server_from_a_source(self):
        self.write("shared/mcp/servers.base.json", json.dumps({"servers": {}}))
        self.add_overlay("work", 60, {"mcp/servers.json": json.dumps({"servers": {"kb": {"command": "/opt/kb"}}})})
        rs.render_codex(self.repo)

        def codex_writes(data):
            data["mcp_servers"]["kb"]["enabled"] = False
            data["mcp_servers"]["mine"] = {"command": "/usr/bin/mine"}

        self.edit_live(codex_writes)
        self.registry.clear()
        self.save_registry()
        rs.render_codex(self.repo)
        self.assertEqual(self.live()["mcp_servers"], {"mine": {"command": "/usr/bin/mine"}})

    def test_a_literal_from_an_earlier_render_does_not_outlive_forwarding(self):
        # A file rendered before env references were forwarded holds the literal
        # in env; once it is forwarded, that key is managed no more and must go.
        root = self.add_overlay("work", 60, {
            "mcp/servers.json": json.dumps({"servers": {"kb": {"command": "kb", "env": {"API_TOKEN": "old"}}}}),
        })
        rs.render_codex(self.repo)
        self.assertEqual(self.live()["mcp_servers"]["kb"]["env"], {"API_TOKEN": "old"})
        (root / "mcp" / "servers.json").write_text(
            json.dumps({"servers": {"kb": {"command": "kb", "env": {"API_TOKEN": "${API_TOKEN}"}}}})
        )
        rs.render_codex(self.repo)
        self.assertEqual(self.live()["mcp_servers"]["kb"], {"command": "kb", "env_vars": ["API_TOKEN"]})

    def test_a_stale_literal_is_dropped_even_without_render_state(self):
        # Codex prefers env over env_vars, so a leftover "${API_TOKEN}" would
        # win. A hand-typed value next to a forwarded name is left alone.
        self.add_overlay("work", 60, {"mcp/servers.json": json.dumps({"servers": {
            "kb": {"command": "kb", "env": {"API_TOKEN": "${API_TOKEN}", "OTHER": "${OTHER}"}}}})})
        (self.repo / rs.CODEX_LIVE_REL).write_text(
            '[mcp_servers.kb]\ncommand = "kb"\nenv = { API_TOKEN = "${API_TOKEN}", OTHER = "typed" }\n'
        )
        rs.render_codex(self.repo)
        self.assertEqual(self.live()["mcp_servers"]["kb"],
                         {"command": "kb", "env_vars": ["API_TOKEN", "OTHER"], "env": {"OTHER": "typed"}})

    def test_a_trailing_plus_is_part_of_a_codex_key(self):
        self.write(
            "shared/mcp/servers.base.json",
            json.dumps({"servers": {"notes+": {"command": "/opt/notes"}}}),
        )
        self.add_overlay("study", 60, {
            "settings/codex.toml": '[projects."${CLAUDE_HOME}/c++"]\ntrust_level = "trusted"\n',
        })
        rs.render_codex(self.repo)
        live = self.live()
        self.assertEqual(live["projects"], {f"{FAKE_HOME}/c++": {"trust_level": "trusted"}})
        self.assertEqual(list(live["mcp_servers"]), ["notes+"])

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

    def test_a_value_of_another_type_is_drift(self):
        # Python's == takes 1 for true and 65536.0 for 65536; Codex refuses both.
        self.write("codex/config.base.toml", (
            'model = "base-model"\nproject_doc_max_bytes = 65536\n\n'
            "[tui]\nscreen_reader_detection_done = true\n"
        ))
        rs.render_codex(self.repo)
        path = self.repo / rs.CODEX_LIVE_REL
        text = path.read_text()
        text = text.replace("screen_reader_detection_done = true", "screen_reader_detection_done = 1")
        path.write_text(text.replace("project_doc_max_bytes = 65536", "project_doc_max_bytes = 65536.0"))
        self.assertFalse(rs.artifact_current(self.repo, rs.CODEX_LIVE_REL, rs.render_codex(self.repo, write=False)))
        rs.render_codex(self.repo)
        live = self.live()
        self.assertIs(live["tui"]["screen_reader_detection_done"], True)
        self.assertIs(type(live["project_doc_max_bytes"]), int)

    def test_a_nan_codex_wrote_is_kept_and_stays_current(self):
        rs.render_codex(self.repo)
        path = self.repo / rs.CODEX_LIVE_REL
        path.write_text("newer_codex_key = nan\n" + path.read_text())
        rs.render_codex(self.repo)
        self.assertTrue(math.isnan(self.live()["newer_codex_key"]))
        before = path.stat().st_mtime_ns
        merged = rs.render_codex(self.repo)
        self.assertTrue(rs.artifact_current(self.repo, rs.CODEX_LIVE_REL, merged))
        self.assertEqual(path.stat().st_mtime_ns, before)

    def codex_writes(self, key: str) -> None:
        """What Codex does on a trust decision or /model: read, add, rename a new file over."""
        path = self.repo / rs.CODEX_LIVE_REL
        data = tomllib.loads(path.read_text())
        data[key] = True
        tmp = path.with_name(".tmpCodex")
        tmp.write_text(rs.dumps_toml(data))
        os.replace(tmp, path)

    def codex_writes_after_reads(self, times: int):
        """Have Codex write right after each of the render's first `times` reads."""
        real = rs._read_live
        written: list[str] = []

        def read_then_codex_writes(path):
            out = real(path)
            if len(written) < times:
                written.append(f"codex_wrote_{len(written)}")
                self.codex_writes(written[-1])
            return out

        return mock.patch.object(rs, "_read_live", read_then_codex_writes), written

    def test_a_codex_write_during_the_render_survives(self):
        self.write(rs.CODEX_LIVE_REL, LIVE)
        rs.render_codex(self.repo)
        self.write("codex/config.base.toml", 'model = "next-model"\n')
        patch, written = self.codex_writes_after_reads(1)
        with patch:
            rs.render_codex(self.repo)
        live = self.live()
        self.assertIn("codex_wrote_0", live)
        self.assertEqual(live["model"], "next-model")
        self.assertEqual(self.mode(), 0o600)

    def test_a_codex_write_during_a_render_with_nothing_to_change_survives(self):
        self.write(rs.CODEX_LIVE_REL, LIVE)
        rs.render_codex(self.repo)
        patch, written = self.codex_writes_after_reads(1)
        with patch:
            rs.render_codex(self.repo)
        self.assertIn("codex_wrote_0", self.live())

    def test_a_file_that_keeps_changing_is_left_to_codex(self):
        self.write(rs.CODEX_LIVE_REL, LIVE)
        rs.render_codex(self.repo)
        self.write("codex/config.base.toml", 'model = "next-model"\n')
        patch, written = self.codex_writes_after_reads(rs.CODEX_RENDER_ATTEMPTS)
        with patch, self.assertRaises(ValueError):
            rs.render_codex(self.repo)
        live = self.live()
        self.assertEqual(len(written), rs.CODEX_RENDER_ATTEMPTS)
        self.assertEqual([key for key in written if key not in live], [])
        self.assertEqual(live["model"], "base-model")
        self.assertFalse((self.repo / "codex" / "config.toml.render-tmp").exists())

    def test_a_directory_in_place_of_the_file(self):
        (self.repo / rs.CODEX_LIVE_REL).mkdir()
        self.assertEqual(rs.render_codex(self.repo, write=False)["model"], "base-model")
        with self.assertRaises(OSError):
            rs.render_codex(self.repo)
        self.assertFalse((self.repo / "codex" / "config.toml.render-tmp").exists())

    def test_a_current_file_with_a_loose_mode_is_made_private_in_place(self):
        # A copy put back with cp or a shell redirect gets the umask's mode and
        # can already hold the render, so no rewrite would make it private.
        rs.render_codex(self.repo)
        path = self.repo / rs.CODEX_LIVE_REL
        path.chmod(0o664)
        inode = path.stat().st_ino
        rs.render_codex(self.repo)
        self.assertEqual(self.mode(), 0o600)
        # A rewrite replaces the file, so the same inode means chmod alone.
        self.assertEqual(path.stat().st_ino, inode)

    def test_status_flags_an_unignored_local_toml(self):
        root = self.add_overlay("personal", 50, {})
        (root / ".gitignore").write_text("*.local.json\n")
        (root / "settings").mkdir()
        (root / "settings" / "codex.local.toml").write_text('model = "x"\n')
        lines: list[str] = []
        overlay_mod.cmd_status(self.repo, None, lines.append)
        self.assertTrue(any(line.startswith("LOCAL personal/settings/codex.local.toml") for line in lines), lines)

    def test_install_warns_about_an_unignored_local_toml(self):
        self.write("claude/settings.base.json", "{}\n")
        root = self.add_overlay("personal", 50, {})
        (root / ".gitignore").write_text("*.local.json\n")
        (root / "settings").mkdir()
        (root / "settings" / "codex.local.toml").write_text('model = "x"\n')
        install = overlay_mod.build_parser().parse_args(["install"])
        lines: list[str] = []
        self.assertEqual(overlay_mod.cmd_install(self.repo, install, lines.append), 0)
        self.assertTrue(any(line.startswith("WARN personal/settings/codex.local.toml") for line in lines), lines)
        self.assertEqual(self.live()["model"], "x")

        (root / ".gitignore").write_text("*.local.json\n*.local.toml\n")
        lines.clear()
        overlay_mod.cmd_install(self.repo, install, lines.append)
        self.assertFalse(any(line.startswith("WARN") for line in lines), lines)


class RenderClaudeSettingsTests(FixtureRepo):
    def test_what_claude_code_added_outlives_the_overlay_that_brought_the_table(self):
        self.write(rs.BASE_REL, json.dumps({"model": "base", "statusLine": {"type": "command", "command": "sl"}}))
        self.add_overlay("work", 60, {"settings/claude.json": json.dumps({"enabledPlugins": {"bsp@work": True}})})
        rs.render(self.repo)
        live_path = self.repo / rs.LIVE_REL
        data = json.loads(live_path.read_text())
        data["enabledPlugins"]["frontend@official"] = True  # /plugin install, user scope
        data["statusLine"]["refreshInterval"] = 5
        live_path.write_text(json.dumps(data))

        self.registry.clear()
        self.save_registry()
        self.write(rs.BASE_REL, json.dumps({"model": "base"}))
        live = rs.render(self.repo)
        self.assertEqual(live["enabledPlugins"], {"frontend@official": True})
        # A status line without type and command would make Claude Code skip the file.
        self.assertNotIn("statusLine", live)


class NoTomlReaderTests(FixtureRepo):
    """Python 3.9 and 3.10 without tomli: Codex is skipped, nothing else is."""

    def setUp(self) -> None:
        super().setUp()
        self.write(rs.BASE_REL, json.dumps({"model": "base-model"}))
        patcher = mock.patch.object(rs, "tomllib", None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_everything_but_codex_still_renders(self):
        self.write(rs.CODEX_LIVE_REL, LIVE)
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            rendered = rs.render_all(self.repo)
        self.assertEqual(json.loads((self.repo / rs.LIVE_REL).read_text()), {"model": "base-model"})
        self.assertIn("linear", json.loads((self.repo / rs.MCP_LIVE_REL).read_text())["servers"])
        self.assertEqual(rendered[rs.CODEX_LIVE_REL], {})
        # What Codex wrote for itself is left exactly as it was.
        self.assertEqual((self.repo / rs.CODEX_LIVE_REL).read_text(), LIVE)
        self.assertIn(rs.NO_TOML_READER, stderr.getvalue())

    def test_check_and_status_pass(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            rc = rs.main(["--repo", str(self.repo), "--check"])
            rs.render_all(self.repo)
        self.assertEqual(rc, 0, out.getvalue())
        self.assertIn(f"SKIP  {rs.CODEX_BASE_REL}", out.getvalue())
        lines: list[str] = []
        with contextlib.redirect_stderr(io.StringIO()):
            overlay_mod.cmd_status(self.repo, None, lines.append)
        self.assertFalse([line for line in lines if line.startswith("DRIFT")], lines)

    def import_with(self, shadows: dict[str, str]) -> str:
        """Import the scripts in a child whose tomllib/tomli are these stand-ins."""
        shim = Path(tempfile.mkdtemp(dir=self._tmp.name))
        for name, source in shadows.items():
            (shim / f"{name}.py").write_text(source)
        result = subprocess.run(
            [sys.executable, "-B", "-c",
             "import overlay, render_settings as rs; print(getattr(rs.tomllib, '__name__', None))"],
            cwd=Path(rs.__file__).resolve().parent,
            env={**os.environ, "PYTHONPATH": str(shim)},
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def test_import_falls_back_to_tomli_then_to_nothing(self):
        missing = "raise ModuleNotFoundError('stand-in for a missing module', name={0!r})\n"
        no_tomllib = missing.format("tomllib")
        self.assertEqual(self.import_with({"tomllib": no_tomllib, "tomli": "loads = None\n"}), "tomli")
        self.assertEqual(self.import_with({"tomllib": no_tomllib, "tomli": missing.format("tomli")}), "None")


@needs_toml
class RenderAllTests(FixtureRepo):
    """A source that does not parse stops the whole render before anything is written."""

    def setUp(self) -> None:
        super().setUp()
        self.write(rs.BASE_REL, json.dumps({"model": "one"}))
        self.work = self.add_overlay("work", 60, {
            "settings/codex.toml": '[projects."${CLAUDE_HOME}/work"]\ntrust_level = "trusted"\n',
        })
        rs.render_all(self.repo)
        # An edit not rendered yet, so a render that writes anything shows it.
        self.write(rs.BASE_REL, json.dumps({"model": "two"}))

    def settings_model(self) -> str:
        return json.loads((self.repo / rs.LIVE_REL).read_text())["model"]

    def assert_render_refused(self, *names: str) -> str:
        with self.assertRaises(ValueError) as caught:
            rs.render_all(self.repo)
        for name in names:
            self.assertIn(name, str(caught.exception))
        self.assertEqual(self.settings_model(), "one")
        return str(caught.exception)

    def test_an_overlay_fragment_that_does_not_parse(self):
        (self.work / "settings" / "codex.toml").write_text("[projects.x]\ntrust_level = trusted\n")
        self.assert_render_refused("work/settings/codex.toml", "does not parse")

    def test_a_base_that_does_not_parse(self):
        self.write("codex/config.base.toml", "model = base-model\n")
        self.assert_render_refused(rs.CODEX_BASE_REL)

    def test_a_live_file_in_toml_1_1(self):
        # Codex 0.163 reads this; tomllib does not.
        with (self.repo / rs.CODEX_LIVE_REL).open("a") as fh:
            fh.write('\n[mcp_servers.hand]\ncommand = "h"\nenv = {\n  A = "1",\n}\n')
        message = self.assert_render_refused(rs.CODEX_LIVE_REL)
        self.assertIn("TOML 1.1", message)

    def test_a_tracked_codex_config(self):
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "add", rs.CODEX_LIVE_REL)
        self.assert_render_refused("tracked by git")

    def test_a_skipped_server_is_reported_once_for_two_passes(self):
        self.write("shared/mcp/servers.base.json", json.dumps({"servers": {"s": {"url": "https://x", "transport": "sse"}}}))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rs.render_all(self.repo)
        self.assertEqual(err.getvalue().count("skipped MCP server 's'"), 1, err.getvalue())
        self.assertEqual(self.settings_model(), "two")

    def test_every_codex_warning_is_printed_once_for_two_passes(self):
        self.write("shared/mcp/servers.base.json", json.dumps({"servers": {
            "linear": {"url": "https://mcp.linear.app/mcp"},
            "kb": {"command": "kb", "env": {"DSN": "pg://${PASS}@h"}},
        }}))
        self.edit_live(lambda data: data["mcp_servers"]["linear"].update(command="npx"))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rs.render_all(self.repo)
        self.assertEqual(err.getvalue().count("'kb' env DSN"), 1, err.getvalue())
        self.assertEqual(err.getvalue().count("dropped command from MCP server 'linear'"), 1, err.getvalue())

    def test_check_reports_a_base_that_does_not_parse(self):
        self.write("codex/config.base.toml", "model = \n")
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = rs.main(["--repo", str(self.repo), "--check"])
        self.assertEqual(code, 1)
        self.assertIn(f"{rs.CODEX_BASE_REL} does not parse", err.getvalue())
        self.assertNotIn("local-only", err.getvalue())

    def test_overlay_commands_print_one_line_not_a_traceback(self):
        (self.work / "settings" / "codex.toml").write_text("trust_level = \n")
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = overlay_mod.main(["--repo", str(self.repo), "install"])
        self.assertEqual(code, 1)
        self.assertIn("overlay: render failed:", err.getvalue())
        self.assertIn("work/settings/codex.toml", err.getvalue())
        self.assertEqual(self.settings_model(), "one")

    def test_status_reports_the_file_and_goes_on(self):
        (self.work / "settings" / "codex.toml").write_text("trust_level = \n")
        lines: list[str] = []
        self.assertEqual(overlay_mod.cmd_status(self.repo, None, lines.append), 1)
        self.assertTrue(any(line.startswith("RENDER ") and "work/settings/codex.toml" in line for line in lines), lines)


@needs_toml
class UntrackingPullTests(FixtureRepo):
    """codex/config.toml was tracked until 2026-10; a pull that untracks it deletes it."""

    def setUp(self) -> None:
        super().setUp()
        self.write(rs.CODEX_LIVE_REL, LIVE)
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "tracked, as before 2026-10")
        # What that pull does to an unmodified copy: gone from the index and the disk.
        git(self.repo, "rm", "-q", rs.CODEX_LIVE_REL)
        git(self.repo, "commit", "-qm", "untracked")

    def test_the_first_render_restores_what_the_pull_deleted(self):
        rs.render_codex(self.repo)
        live = self.live()
        self.assertEqual(live["projects"], {"/somewhere/else": {"trust_level": "trusted"}})
        self.assertEqual(live["newer_codex_key"], 7)
        self.assertEqual(live["model"], "base-model")
        self.assertEqual(self.mode(), 0o600)

    def test_a_clone_made_after_the_untracking_starts_from_the_sources(self):
        clone = Path(self._tmp.name) / "clone"
        git(self.repo, "clone", "-q", str(self.repo), str(clone))
        self.assertIsNone(rs.last_checked_out_copy(clone, rs.CODEX_LIVE_REL))
        rs.render_codex(clone)
        self.assertNotIn("projects", tomllib.loads((clone / rs.CODEX_LIVE_REL).read_text()))

    def test_orig_head_stands_in_for_an_expired_reflog(self):
        git(self.repo, "reflog", "expire", "--expire=now", "--all")
        git(self.repo, "update-ref", "ORIG_HEAD", "HEAD~1")  # what the pull set
        rs.render_codex(self.repo)
        self.assertEqual(self.live()["projects"], {"/somewhere/else": {"trust_level": "trusted"}})

    def test_render_all_restores_once_and_says_so_once(self):
        self.write(rs.BASE_REL, json.dumps({"model": "m"}))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rs.render_all(self.repo)
        self.assertEqual(err.getvalue().count("restored codex/config.toml"), 1, err.getvalue())
        self.assertEqual(self.live()["newer_codex_key"], 7)

    def test_a_file_removed_after_the_first_render_stays_removed(self):
        rs.render_codex(self.repo)
        (self.repo / rs.CODEX_LIVE_REL).unlink()
        rs.render_codex(self.repo)
        self.assertNotIn("projects", self.live())


class EntryPointTests(unittest.TestCase):
    def test_the_scripts_the_readme_runs_directly_are_executable(self):
        scripts = Path(__file__).resolve().parent
        for name in ("render_settings.py", "overlay.py"):
            self.assertTrue(os.access(scripts / name, os.X_OK), name)


class PrivateArtifactTests(FixtureRepo):
    """servers.json carries the same credentials as codex/config.toml."""

    def servers_mode(self) -> int:
        return (self.repo / rs.MCP_LIVE_REL).stat().st_mode & 0o777

    def test_servers_file_is_private_under_a_group_writable_umask(self):
        old = os.umask(0o002)
        try:
            rs.render_mcp(self.repo)
        finally:
            os.umask(old)
        self.assertEqual(self.servers_mode(), 0o600)

    def test_a_current_but_loose_servers_file_is_tightened_in_place(self):
        rs.render_mcp(self.repo)
        path = self.repo / rs.MCP_LIVE_REL
        path.chmod(0o664)
        before = path.stat().st_mtime_ns
        rs.render_mcp(self.repo)
        self.assertEqual(self.servers_mode(), 0o600)
        self.assertEqual(path.stat().st_mtime_ns, before)

    def test_a_current_file_that_cannot_be_chmod_ed_is_replaced(self):
        # A servers.json a render under sudo left behind: chmod is refused,
        # but replacing it needs only the directory.
        rs.render_mcp(self.repo)
        path = self.repo / rs.MCP_LIVE_REL
        path.chmod(0o644)
        inode = path.stat().st_ino
        with mock.patch.object(rs.os, "chmod", side_effect=PermissionError(1, "Operation not permitted")):
            rs.render_mcp(self.repo)
        self.assertEqual(self.servers_mode(), 0o600)
        self.assertNotEqual(path.stat().st_ino, inode)

    @needs_toml
    def test_template_codex_fragment_grants_no_trust(self):
        # overlay.py init copies the template into every new overlay.
        text = (REPO_ROOT / "templates/overlay-example/settings/codex.toml").read_text()
        self.assertEqual(tomllib.loads(text), {})
        self.add_overlay("fresh", 50, {"settings/codex.toml": text})
        rs.render_codex(self.repo)
        self.assertNotIn("projects", self.live())

    def test_gitignore_takes_in_hand_copies_but_not_the_bases(self):
        root = Path(self._tmp.name) / "ignore"
        root.mkdir()
        (root / ".gitignore").write_text((REPO_ROOT / ".gitignore").read_text())
        git(root, "init", "-q")

        def ignored(rel: str) -> bool:
            # Only this repo's rules: a developer's global excludes must not decide.
            probe = ["git", "-c", f"core.excludesFile={os.devnull}", "check-ignore", "-q", "--no-index", rel]
            return subprocess.run(probe, cwd=root, capture_output=True).returncode == 0

        for rel in (
            "codex/config.toml",
            "codex/config.toml.bak",
            "codex/config.toml.bak.20261027-120000",
            "codex/config.toml.orig",
            "codex/config.toml~",
            "shared/mcp/servers.json",
            "shared/mcp/servers.json.bak",
            "claude/settings.json.bak.20261027-120000",
            "codex/db-backups/sqlite-1-0/logs_2.sqlite",
        ):
            self.assertTrue(ignored(rel), rel)
        for rel in ("codex/config.base.toml", "shared/mcp/servers.base.json", "claude/settings.base.json"):
            self.assertFalse(ignored(rel), rel)


class OverlaysDirTests(FixtureRepo):
    def test_saving_the_registry_closes_overlays_to_other_users(self):
        (self.repo / "overlays").chmod(0o775)
        overlay_mod.save_registry(self.repo, [])
        self.assertEqual((self.repo / "overlays").stat().st_mode & 0o777, 0o700)

    def test_init_scaffolds_into_a_closed_overlays_dir(self):
        (self.repo / "overlays").rmdir()
        template = self.repo / overlay_mod.TEMPLATE_REL
        template.mkdir(parents=True)
        (template / "overlay.json").write_text(json.dumps({"name": "example"}))
        args = type("Args", (), {"dest": "fresh", "name": None})()
        overlay_mod.cmd_init(self.repo, args, lambda _msg: None)
        self.assertEqual((self.repo / "overlays").stat().st_mode & 0o777, 0o700)


class ClaudeSettingsCurrentTests(FixtureRepo):
    def setUp(self) -> None:
        super().setUp()
        self.write(rs.BASE_REL, json.dumps({"idleCompaction": False, "hooks": {"Stop": [{"timeout": 120.0}]}}))
        rs.render(self.repo)
        self.path = self.repo / rs.LIVE_REL

    def test_a_number_for_a_boolean_is_drift(self):
        # Claude Code refuses the whole file over it, hooks and permissions included.
        data = json.loads(self.path.read_text())
        data["idleCompaction"] = 0
        self.path.write_text(json.dumps(data))
        self.assertFalse(rs.artifact_current(self.repo, rs.LIVE_REL, rs.render(self.repo, write=False)))
        rs.render(self.repo)
        self.assertIs(json.loads(self.path.read_text())["idleCompaction"], False)

    def test_one_json_number_is_not_drift(self):
        # Claude Code writes the 120.0 a source holds back as 120.
        data = json.loads(self.path.read_text())
        data["hooks"]["Stop"][0]["timeout"] = 120
        self.path.write_text(json.dumps(data))
        before = self.path.stat().st_mtime_ns
        merged = rs.render(self.repo)
        self.assertTrue(rs.artifact_current(self.repo, rs.LIVE_REL, merged))
        self.assertEqual(self.path.stat().st_mtime_ns, before)


class PrivateServersTests(FixtureRepo):
    """servers.json holds the same overlay credentials as codex/config.toml."""

    def setUp(self) -> None:
        super().setUp()
        root = self.add_overlay("work", 60, {
            "mcp/servers.json": json.dumps({"servers": {"kb": {
                "url": "https://kb.example.invalid/mcp", "headers": {"Authorization": "Bearer ${KB_TOKEN}"}}}}),
        })
        (root / "vars.local.json").write_text(json.dumps({"KB_TOKEN": "fake-token"}))

    def servers_mode(self) -> int:
        return (self.repo / rs.MCP_LIVE_REL).stat().st_mode & 0o777

    @needs_toml
    def test_every_file_holding_the_credential_is_private(self):
        servers = rs.render_mcp(self.repo)
        rs.render_codex(self.repo, servers=servers)
        for rel in (rs.MCP_LIVE_REL, rs.CODEX_LIVE_REL):
            path = self.repo / rel
            self.assertIn("fake-token", path.read_text(), rel)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600, rel)

    def test_a_current_file_left_readable_is_narrowed_not_rewritten(self):
        rs.render_mcp(self.repo)
        path = self.repo / rs.MCP_LIVE_REL
        path.chmod(0o664)
        before = path.stat().st_mtime_ns
        rs.render_mcp(self.repo)
        self.assertEqual(self.servers_mode(), 0o600)
        self.assertEqual(path.stat().st_mtime_ns, before)


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
        # language.md's own "# Language" goes: AGENTS.md's "## Language" already
        # heads the section. Kept, it would be demoted into a second "## Language".
        lines = text.splitlines()
        self.assertEqual(lines.count("## Language"), 1)
        self.assertNotIn("# Language", lines)
        self.assertIn("### Detail", text)
        self.assertIn(f"]({shared}/instructions/git-workflow.md)", text)
        self.assertIn(f"]({shared}/memory/MEMORY.md)", text)
        self.assertIn("# a shell comment, not a heading", text)
        self.assertNotIn("## a shell comment", text)
        # personal.md is absent without an overlay, so its line goes.
        self.assertNotIn("instructions/personal.md", text)
        self.assertEqual((self.repo / rs.CODEX_AGENTS_REL).read_text(), text)

    def test_text_after_a_link_is_kept_above_the_body(self):
        self.write("shared/instructions/personal.md", "# Personal\n\n- Call me J.\n")
        text = rs.render_codex_agents(self.repo, write=False)
        root = os.path.abspath(self.repo)
        line = (f"See [instructions/personal.md]({root}/shared/instructions/personal.md) — from an overlay. "
                f"See [docs/overlay.md]({root}/docs/overlay.md).")
        self.assertIn(f"## Personal context\n\n{line}\n\n- Call me J.\n", text)
        # A line that is only the link still gives way to the body.
        self.assertNotIn("See [instructions/language.md]", text)

    def test_links_with_an_anchor_or_without_dot_slash_are_inlined(self):
        self.write("shared/AGENTS.md", (
            "# T\n\n## A\n\nSee [language](./instructions/language.md#detail).\n\n"
            "## B\n\nSee [language](instructions/language.md).\n"
        ))
        text = rs.render_codex_agents(self.repo, write=False)
        self.assertEqual(text.count("- Reply in Korean."), 2)
        self.assertNotIn("See [language]", text)

    def test_a_fence_closes_only_on_its_own_marker(self):
        self.write("shared/instructions/language.md", (
            "# Language\n\n"
            "~~~\n```\n~~~\n\n## After mixed\n\n[y](./y.md)\n\n"
            "````markdown\n```sh\n## inside\n[z](./z.md)\n```\n````\n\n## After nested\n"
        ))
        text = rs.render_codex_agents(self.repo, write=False)
        shared = os.path.abspath(self.repo / "shared")
        self.assertIn("\n### After mixed\n", text)
        self.assertIn(f"[y]({shared}/instructions/y.md)", text)
        self.assertIn("\n## inside\n[z](./z.md)\n", text)
        self.assertIn("\n### After nested\n", text)

    def test_a_link_line_in_a_code_block_of_agents_md_is_copied(self):
        example = "```markdown\nSee [instructions/language.md](./instructions/language.md).\n[m](./m.md)\n```\n"
        self.write("shared/AGENTS.md", f"# T\n\n## Example\n\n{example}")
        text = rs.render_codex_agents(self.repo, write=False)
        self.assertIn(example, text)
        self.assertNotIn("- Reply in Korean.", text)

    def test_titles_and_reference_definitions_are_made_absolute(self):
        self.write("shared/instructions/language.md", (
            '# Language\n\n[t](./y.md "Title") [bare](y.md) [anchor](./y.md#part)\n\n'
            "[r1]: ./y.md\n[r2]: y.md 'Title'\n[Note]: keep this prose as it is\n\n"
            "[web](https://example.com/a.md) [here](#x) [abs](/etc/hosts)\n"
        ))
        text = rs.render_codex_agents(self.repo, write=False)
        y = os.path.abspath(self.repo / "shared/instructions/y.md")
        self.assertIn(f'[t]({y} "Title") [bare]({y}) [anchor]({y}#part)', text)
        self.assertIn(f"[r1]: {y}\n[r2]: {y} 'Title'\n[Note]: keep this prose as it is\n", text)
        self.assertIn("[web](https://example.com/a.md) [here](#x) [abs](/etc/hosts)", text)

    def test_code_spans_and_footnotes_keep_their_text(self):
        self.write("shared/instructions/language.md", (
            "# Language\n\nWrite links as `[text](path.md)`, not [this](./y.md).\n\n[^1]: Done.\n"
        ))
        text = rs.render_codex_agents(self.repo, write=False)
        y = os.path.abspath(self.repo / "shared/instructions/y.md")
        self.assertIn(f"Write links as `[text](path.md)`, not [this]({y}).", text)
        self.assertIn("\n[^1]: Done.\n", text)


if __name__ == "__main__":
    unittest.main()
