"""mcp_server_set / mcp_server_remove — write routing and credential rules."""

from __future__ import annotations

import json

from tests._helpers import HarnessTestCase, make_overlay, register_and_install


class McpServerTests(HarnessTestCase):
    def setUp(self) -> None:
        super().setUp()
        from integrated_harness_kit_mcp.tools import mcp_servers

        self.tool = mcp_servers
        make_overlay(self.repo, "work", priority=60, servers={"kb": {"command": "/opt/kb"}})
        register_and_install(self.repo, "work", priority=60)

    def base(self) -> dict:
        return json.loads((self.repo / "shared" / "mcp" / "servers.base.json").read_text())["servers"]

    def effective(self) -> dict:
        return json.loads((self.repo / "shared" / "mcp" / "servers.json").read_text())["servers"]

    def test_set_on_base_writes_the_base_and_renders(self):
        result = self.tool.mcp_server_set(
            "linear2", url="https://example.com/mcp", repo_path=str(self.repo)
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["wrote"], "shared/mcp/servers.base.json")
        self.assertIn("linear2", self.base())
        self.assertIn("linear2", self.effective())

    def test_overlay_servers_survive_a_base_write(self):
        self.tool.mcp_server_set("linear2", url="https://example.com/mcp", repo_path=str(self.repo))
        self.assertIn("kb", self.effective())

    def test_credentials_are_refused_on_the_public_base(self):
        result = self.tool.mcp_server_set(
            "leaky",
            command="/bin/true",
            env={"TOKEN": "secret"},
            repo_path=str(self.repo),
        )
        self.assertFalse(result["ok"])
        self.assertIn("public", result["error"])
        self.assertNotIn("leaky", self.base())

    def test_credentials_are_allowed_in_an_overlay(self):
        result = self.tool.mcp_server_set(
            "kb",
            command="/opt/kb",
            env={"PASSWORD": "hunter2"},
            target="overlay:work",
            repo_path=str(self.repo),
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["secrets_written"], ["env"])
        fragment = json.loads((self.repo / "overlays" / "work" / "mcp" / "servers.json").read_text())
        self.assertEqual(fragment["servers"]["kb"]["env"]["PASSWORD"], "hunter2")
        self.assertNotIn("hunter2", (self.repo / "shared" / "mcp" / "servers.base.json").read_text())

    def test_exactly_one_of_url_or_command(self):
        both = self.tool.mcp_server_set("x", url="u", command="c", repo_path=str(self.repo))
        neither = self.tool.mcp_server_set("x", repo_path=str(self.repo))
        self.assertFalse(both["ok"])
        self.assertFalse(neither["ok"])

    def test_update_reports_updated_not_added(self):
        self.tool.mcp_server_set("dup", url="https://a", repo_path=str(self.repo))
        second = self.tool.mcp_server_set("dup", url="https://b", repo_path=str(self.repo))
        self.assertEqual(second["action"], "updated")
        self.assertEqual(self.base()["dup"]["url"], "https://b")

    def test_remove_from_base(self):
        self.tool.mcp_server_set("gone", url="https://a", repo_path=str(self.repo))
        result = self.tool.mcp_server_remove("gone", repo_path=str(self.repo))
        self.assertTrue(result["ok"], result)
        self.assertNotIn("gone", self.base())
        self.assertNotIn("gone", self.effective())

    def test_remove_missing_server_lists_what_is_there(self):
        result = self.tool.mcp_server_remove("ghost", repo_path=str(self.repo))
        self.assertFalse(result["ok"])
        self.assertIn("linear", result["defined_here"])

    def test_remove_from_overlay(self):
        result = self.tool.mcp_server_remove("kb", target="overlay:work", repo_path=str(self.repo))
        self.assertTrue(result["ok"], result)
        self.assertNotIn("kb", self.effective())

    def test_unknown_overlay_target(self):
        result = self.tool.mcp_server_set("x", url="u", target="overlay:ghost", repo_path=str(self.repo))
        self.assertFalse(result["ok"])
