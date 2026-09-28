"""list_content / list_mcp_servers — provenance and credential withholding."""

from __future__ import annotations

from tests._helpers import HarnessTestCase, make_overlay, register_and_install, write_command, write_skill


class ListContentTests(HarnessTestCase):
    def setUp(self) -> None:
        super().setUp()
        from integrated_harness_kit_mcp.tools import listing

        self.listing = listing
        write_skill(self.repo, "base-skill", description="from base")
        write_command(self.repo, "base-cmd", description="base command")
        make_overlay(
            self.repo,
            "work",
            priority=60,
            memories={"internal": "---\nname: internal\ndescription: internal host\n---\n\nx\n"},
        )
        register_and_install(self.repo, "work", priority=60)

    def call(self, kind: str) -> dict:
        return self.listing.list_content(kind, repo_path=str(self.repo))

    def test_unknown_kind_is_rejected(self):
        result = self.call("nonsense")
        self.assertFalse(result["ok"])
        self.assertIn("unknown kind", result["error"])

    def test_base_entries_are_tagged_base(self):
        entries = self.call("skills")["entries"]
        self.assertEqual([e["name"] for e in entries], ["base-skill"])
        self.assertEqual(entries[0]["source"], {"kind": "base"})
        self.assertEqual(entries[0]["description"], "from base")

    def test_overlay_entries_carry_their_alias(self):
        entries = {e["name"]: e for e in self.call("memory")["entries"]}
        self.assertIn("internal", entries)
        self.assertEqual(entries["internal"]["source"], {"kind": "overlay", "alias": "work"})

    def test_memory_index_is_not_listed_as_content(self):
        (self.repo / "shared" / "memory" / "MEMORY.md").write_text("- [x](x.md)\n")
        names = [e["name"] for e in self.call("memory")["entries"]]
        self.assertNotIn("MEMORY", names)

    def test_empty_directory_is_not_an_error(self):
        result = self.call("subagents")
        self.assertTrue(result["ok"])
        self.assertEqual(result["entries"], [])


class ListMcpServersTests(HarnessTestCase):
    def setUp(self) -> None:
        super().setUp()
        from integrated_harness_kit_mcp.tools import listing

        self.listing = listing
        make_overlay(
            self.repo,
            "work",
            priority=60,
            servers={
                "internal-kb": {
                    "description": "internal",
                    "command": "/opt/kb-serve",
                    "args": [],
                    "env": {"PASSWORD": "hunter2", "HOST": "kb.internal"},
                }
            },
        )
        register_and_install(self.repo, "work", priority=60)

    def call(self, scope: str = "effective") -> dict:
        return self.listing.list_mcp_servers(scope=scope, repo_path=str(self.repo))

    def test_effective_includes_overlay_servers(self):
        names = [entry["name"] for entry in self.call("effective")["effective"]]
        self.assertEqual(names, ["internal-kb", "linear"])

    def test_base_scope_excludes_overlay_servers(self):
        names = [entry["name"] for entry in self.call("base")["base"]]
        self.assertEqual(names, ["linear"])

    def test_overlay_only_is_reported(self):
        self.assertEqual(self.call("both")["overlay_only"], ["internal-kb"])

    def test_credentials_are_never_returned(self):
        entry = next(e for e in self.call("effective")["effective"] if e["name"] == "internal-kb")
        self.assertNotIn("env", entry)
        self.assertNotIn("headers", entry)
        self.assertEqual(entry["withheld"], ["env"])
        self.assertNotIn("hunter2", str(self.call("both")))

    def test_unknown_scope_is_rejected(self):
        self.assertFalse(self.call("sideways")["ok"])
