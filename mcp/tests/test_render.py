"""render — the three scopes, and the leak the public scope exists to prevent."""

from __future__ import annotations

import json

from tests._helpers import (
    HarnessTestCase,
    make_overlay,
    register_and_install,
    write_claude_json,
)

# Stand-ins for the repo's shell renderers: they do the one thing that matters
# here — copy whatever servers.json holds into a tracked per-tool config.
RENDER_MCP_STUB = """#!/usr/bin/env bash
set -e
python3 - "$PWD" <<'PY'
import json, sys
from pathlib import Path
repo = Path(sys.argv[1])
servers = json.loads((repo / "shared/mcp/servers.json").read_text()).get("servers", {})
(repo / "codex").mkdir(exist_ok=True)
(repo / "codex" / "config.toml").write_text(
    "".join(f"[mcp_servers.{name}]\\n" for name in sorted(servers)))
PY
"""

RENDER_COMMANDS_STUB = """#!/usr/bin/env bash
mkdir -p gemini/commands
echo "rendered" > gemini/commands/.stamp
"""


class RenderArtifactsTests(HarnessTestCase):
    def setUp(self) -> None:
        super().setUp()
        from integrated_harness_kit_mcp.tools import render as render_mod

        self.render = render_mod.render

    def test_artifacts_are_written_from_the_bases(self):
        result = self.render(scope="artifacts", repo_path=str(self.repo))
        self.assertTrue(result["ok"], result)
        for rel in (
            "claude/settings.json",
            "shared/mcp/servers.json",
            "shared/memory/MEMORY.md",
        ):
            self.assertTrue((self.repo / rel).is_file(), rel)

    def test_overlay_content_reaches_the_artifacts(self):
        make_overlay(
            self.repo,
            "work",
            priority=60,
            settings={"model": "work-model"},
            servers={"kb": {"command": "/opt/kb"}},
            index_lines=["- [internal](internal.md) — private"],
        )
        register_and_install(self.repo, "work", priority=60)
        self.render(scope="artifacts", repo_path=str(self.repo))

        settings = json.loads((self.repo / "claude" / "settings.json").read_text())
        servers = json.loads((self.repo / "shared" / "mcp" / "servers.json").read_text())
        memory = (self.repo / "shared" / "memory" / "MEMORY.md").read_text()
        self.assertEqual(settings["model"], "work-model")
        self.assertIn("kb", servers["servers"])
        self.assertIn("internal", memory)

    def test_unknown_scope_is_rejected(self):
        self.assertFalse(self.render(scope="sideways", repo_path=str(self.repo))["ok"])

    def test_missing_render_script_is_reported(self):
        (self.repo / "scripts" / "render_settings.py").unlink()
        from integrated_harness_kit_mcp import repo_scripts

        repo_scripts.clear_cache()
        result = self.render(scope="artifacts", repo_path=str(self.repo))
        self.assertFalse(result["ok"])


class RenderPublicTests(HarnessTestCase):
    def setUp(self) -> None:
        super().setUp()
        from integrated_harness_kit_mcp.tools import render as render_mod

        self.render = render_mod.render
        for name, body in (
            ("render-mcp.sh", RENDER_MCP_STUB),
            ("render-gemini-commands.sh", RENDER_COMMANDS_STUB),
        ):
            script = self.repo / "scripts" / name
            script.write_text(body)
            script.chmod(0o755)

        make_overlay(self.repo, "work", priority=60, servers={"internal-kb": {"command": "/opt/kb"}})
        register_and_install(self.repo, "work", priority=60)

    def codex(self) -> str:
        return (self.repo / "codex" / "config.toml").read_text()

    def test_public_render_excludes_overlay_servers(self):
        result = self.render(scope="public", repo_path=str(self.repo))
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["steps"][0]["overlay_servers_excluded"], ["internal-kb"])
        self.assertIn("linear", self.codex())
        self.assertNotIn("internal-kb", self.codex())

    def test_effective_servers_are_restored_afterwards(self):
        before = (self.repo / "shared" / "mcp" / "servers.json").read_text()
        self.render(scope="public", repo_path=str(self.repo))
        after = (self.repo / "shared" / "mcp" / "servers.json").read_text()
        self.assertEqual(before, after)
        self.assertIn("internal-kb", after)

    def test_a_pre_existing_leak_is_reported(self):
        (self.repo / "codex" / "config.toml").write_text("[mcp_servers.internal-kb]\n")
        # The stub rewrites the file, so simulate a renderer that leaves the leak.
        (self.repo / "scripts" / "render-mcp.sh").write_text("#!/usr/bin/env bash\nexit 0\n")
        (self.repo / "scripts" / "render-mcp.sh").chmod(0o755)
        result = self.render(scope="public", repo_path=str(self.repo))
        step = result["steps"][0]
        self.assertFalse(step["ok"])
        self.assertEqual(step["leak"][0]["servers"], ["internal-kb"])

    def test_without_overlays_nothing_is_swapped(self):
        from integrated_harness_kit_mcp.tools.overlay import overlay_remove

        overlay_remove("work", repo_path=str(self.repo))
        result = self.render(scope="public", repo_path=str(self.repo))
        self.assertEqual(result["steps"][0]["rendered_from"], "servers.json")
        self.assertTrue(result["ok"], result)


class RenderLocalTests(HarnessTestCase):
    def setUp(self) -> None:
        super().setUp()
        from integrated_harness_kit_mcp.tools import render as render_mod

        self.render = render_mod.render
        make_overlay(
            self.repo,
            "work",
            priority=60,
            servers={"kb": {"command": "/opt/kb", "env": {"HOST": "kb.internal"}}},
        )
        register_and_install(self.repo, "work", priority=60)

    def test_local_gets_the_effective_set(self):
        write_claude_json(self.home, {})
        result = self.render(scope="local", repo_path=str(self.repo), home=str(self.home))
        self.assertTrue(result["ok"], result)
        live = json.loads((self.home / ".claude.json").read_text())
        self.assertIn("kb", live["mcpServers"])
        self.assertEqual(live["other"], "keep")

    def test_a_password_only_this_machine_has_is_preserved(self):
        write_claude_json(
            self.home,
            {"kb": {"command": "/opt/kb", "env": {"PASSWORD": "hunter2", "HOST": "old"}}},
        )
        result = self.render(scope="local", repo_path=str(self.repo), home=str(self.home))
        live = json.loads((self.home / ".claude.json").read_text())
        self.assertEqual(live["mcpServers"]["kb"]["env"]["PASSWORD"], "hunter2")
        self.assertEqual(live["mcpServers"]["kb"]["env"]["HOST"], "kb.internal")
        self.assertIn("kb.env.PASSWORD", result["steps"][0]["preserved_local_values"])

    def test_unrelated_servers_are_left_alone(self):
        write_claude_json(self.home, {"someone-elses": {"command": "/bin/true"}})
        self.render(scope="local", repo_path=str(self.repo), home=str(self.home))
        live = json.loads((self.home / ".claude.json").read_text())
        self.assertIn("someone-elses", live["mcpServers"])

    def test_missing_claude_json_is_an_error_not_a_crash(self):
        result = self.render(scope="local", repo_path=str(self.repo), home=str(self.home))
        self.assertFalse(result["steps"][0]["ok"])
        self.assertIn("not found", result["steps"][0]["error"])
