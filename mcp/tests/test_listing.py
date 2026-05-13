"""Tests for the list_* tools."""

from __future__ import annotations

import unittest

from tests._helpers import (
    TmpRepoTestCase,
    write_command,
    write_mcp_servers,
    write_skill,
    write_subagent,
)
from harness_adapter_mcp.tools.listing import (
    list_commands,
    list_mcp_servers,
    list_skills,
    list_subagents,
)


class ListSkillsTestCase(TmpRepoTestCase):
    def test_empty_when_no_skills(self):
        self.assertEqual(list_skills(repo_path=str(self.repo)), [])

    def test_lists_one_skill(self):
        write_skill(self.repo, "thinker", description="thinks hard")
        result = list_skills(repo_path=str(self.repo))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "thinker")
        self.assertEqual(result[0]["description"], "thinks hard")

    def test_skips_dirs_without_skill_md(self):
        # A bare directory under skills/ with no SKILL.md should not show up.
        (self.repo / "universal" / "skills" / "incomplete").mkdir()
        self.assertEqual(list_skills(repo_path=str(self.repo)), [])


class ListMcpTestCase(TmpRepoTestCase):
    def test_empty_when_servers_json_missing(self):
        self.assertEqual(list_mcp_servers(repo_path=str(self.repo)), [])

    def test_lists_remote_and_stdio(self):
        write_mcp_servers(
            self.repo,
            {
                "linear": {
                    "description": "Linear",
                    "url": "https://mcp.linear.app/mcp",
                    "transport": "http",
                },
                "fs": {
                    "command": "npx",
                    "args": ["-y", "fs-server"],
                },
            },
        )
        result = list_mcp_servers(repo_path=str(self.repo))
        by_name = {s["name"]: s for s in result}
        self.assertEqual(by_name["linear"]["url"], "https://mcp.linear.app/mcp")
        self.assertEqual(by_name["linear"]["transport"], "http")
        self.assertEqual(by_name["fs"]["command"], "npx")
        self.assertEqual(by_name["fs"]["args"], ["-y", "fs-server"])


class ListCommandsTestCase(TmpRepoTestCase):
    def test_lists_commands(self):
        write_command(self.repo, "commit", description="make a commit")
        result = list_commands(repo_path=str(self.repo))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "commit")
        self.assertEqual(result[0]["description"], "make a commit")


class ListSubagentsTestCase(TmpRepoTestCase):
    def test_lists_subagents(self):
        write_subagent(self.repo, "code-reviewer", description="reviews code")
        result = list_subagents(repo_path=str(self.repo))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "code-reviewer")
        self.assertEqual(result[0]["description"], "reviews code")


if __name__ == "__main__":
    unittest.main()
