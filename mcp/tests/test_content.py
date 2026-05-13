"""Tests for the content add/remove tools (v0.4)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tests._helpers import (
    TmpRepoTestCase,
    write_command,
    write_mcp_servers,
    write_skill,
    write_subagent,
)
from integrated_harness_kit_mcp.tools.content import (
    add_command,
    add_mcp_server,
    add_skill,
    add_subagent,
    remove_command,
    remove_mcp_server,
    remove_skill,
    remove_subagent,
)


def _install_noop_render(repo: Path, name: str) -> None:
    """Install a render stub that succeeds without doing anything."""
    s = repo / "scripts" / name
    s.write_text('#!/usr/bin/env bash\nexit 0\n')
    s.chmod(0o755)


class AddSkillTestCase(TmpRepoTestCase):
    def test_creates_skill(self):
        result = add_skill(
            name="my-skill",
            description="Does the thing",
            body="When to use: ...",
            repo_path=str(self.repo),
        )
        self.assertTrue(result["ok"])
        skill_md = self.repo / "universal" / "skills" / "my-skill" / "SKILL.md"
        self.assertTrue(skill_md.is_file())
        text = skill_md.read_text()
        self.assertIn("name: my-skill", text)
        self.assertIn("description: Does the thing", text)
        self.assertIn("When to use", text)

    def test_refuses_overwrite(self):
        write_skill(self.repo, "existing")
        result = add_skill(
            name="existing",
            description="x",
            body="y",
            repo_path=str(self.repo),
        )
        self.assertFalse(result["ok"])
        self.assertIn("already exists", result["error"])

    def test_rejects_bad_name(self):
        result = add_skill(
            name="../escape",
            description="x",
            body="y",
            repo_path=str(self.repo),
        )
        self.assertFalse(result["ok"])
        self.assertIn("name", result["error"])

    def test_rejects_empty_description(self):
        result = add_skill(
            name="x",
            description="   ",
            body="y",
            repo_path=str(self.repo),
        )
        self.assertFalse(result["ok"])


class RemoveSkillTestCase(TmpRepoTestCase):
    def test_removes_skill(self):
        write_skill(self.repo, "tmp-skill")
        result = remove_skill("tmp-skill", repo_path=str(self.repo))
        self.assertTrue(result["ok"])
        self.assertFalse((self.repo / "universal" / "skills" / "tmp-skill").exists())

    def test_missing_skill(self):
        result = remove_skill("nope", repo_path=str(self.repo))
        self.assertFalse(result["ok"])
        self.assertIn("not found", result["error"])


class AddMcpServerTestCase(TmpRepoTestCase):
    def setUp(self):
        super().setUp()
        _install_noop_render(self.repo, "render-mcp.sh")

    def test_adds_remote_server(self):
        result = add_mcp_server(
            name="linear",
            description="Linear",
            url="https://mcp.linear.app/mcp",
            transport="http",
            repo_path=str(self.repo),
        )
        self.assertTrue(result["ok"], msg=result)
        servers = json.loads(
            (self.repo / "shared" / "mcp" / "servers.json").read_text()
        )["servers"]
        self.assertIn("linear", servers)
        self.assertEqual(servers["linear"]["url"], "https://mcp.linear.app/mcp")
        self.assertEqual(servers["linear"]["transport"], "http")

    def test_adds_stdio_server(self):
        result = add_mcp_server(
            name="fs",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
            repo_path=str(self.repo),
        )
        self.assertTrue(result["ok"], msg=result)
        servers = json.loads(
            (self.repo / "shared" / "mcp" / "servers.json").read_text()
        )["servers"]
        self.assertEqual(servers["fs"]["command"], "npx")
        self.assertEqual(servers["fs"]["args"][0], "-y")

    def test_rejects_both_url_and_command(self):
        result = add_mcp_server(
            name="x",
            url="https://x",
            command="y",
            repo_path=str(self.repo),
        )
        self.assertFalse(result["ok"])

    def test_rejects_neither_url_nor_command(self):
        result = add_mcp_server(name="x", repo_path=str(self.repo))
        self.assertFalse(result["ok"])

    def test_refuses_duplicate(self):
        write_mcp_servers(self.repo, {"linear": {"url": "x"}})
        result = add_mcp_server(
            name="linear", url="y", repo_path=str(self.repo)
        )
        self.assertFalse(result["ok"])
        self.assertIn("already exists", result["error"])


class RemoveMcpServerTestCase(TmpRepoTestCase):
    def setUp(self):
        super().setUp()
        _install_noop_render(self.repo, "render-mcp.sh")

    def test_removes(self):
        write_mcp_servers(self.repo, {"linear": {"url": "x"}})
        result = remove_mcp_server("linear", repo_path=str(self.repo))
        self.assertTrue(result["ok"], msg=result)
        data = json.loads(
            (self.repo / "shared" / "mcp" / "servers.json").read_text()
        )
        self.assertNotIn("linear", data["servers"])

    def test_missing(self):
        write_mcp_servers(self.repo, {"linear": {"url": "x"}})
        result = remove_mcp_server("other", repo_path=str(self.repo))
        self.assertFalse(result["ok"])
        self.assertIn("not found", result["error"])


class AddCommandTestCase(TmpRepoTestCase):
    def setUp(self):
        super().setUp()
        _install_noop_render(self.repo, "render-gemini-commands.sh")

    def test_creates_command(self):
        result = add_command(
            name="commit",
            description="Make a commit",
            body="Run `git diff --cached`. $ARGUMENTS",
            repo_path=str(self.repo),
        )
        self.assertTrue(result["ok"], msg=result)
        md = self.repo / "shared" / "commands" / "commit.md"
        self.assertTrue(md.is_file())
        text = md.read_text()
        self.assertIn("description: Make a commit", text)
        self.assertIn("$ARGUMENTS", text)

    def test_refuses_duplicate(self):
        write_command(self.repo, "commit")
        result = add_command(
            name="commit", description="x", body="y", repo_path=str(self.repo)
        )
        self.assertFalse(result["ok"])


class RemoveCommandTestCase(TmpRepoTestCase):
    def setUp(self):
        super().setUp()
        _install_noop_render(self.repo, "render-gemini-commands.sh")

    def test_removes(self):
        write_command(self.repo, "commit")
        result = remove_command("commit", repo_path=str(self.repo))
        self.assertTrue(result["ok"])
        self.assertFalse((self.repo / "shared" / "commands" / "commit.md").exists())

    def test_missing(self):
        result = remove_command("nope", repo_path=str(self.repo))
        self.assertFalse(result["ok"])


class AddSubagentTestCase(TmpRepoTestCase):
    def test_creates(self):
        result = add_subagent(
            name="reviewer",
            description="Reviews code",
            body="You are a reviewer.",
            repo_path=str(self.repo),
        )
        self.assertTrue(result["ok"], msg=result)
        md = self.repo / "shared" / "subagents" / "reviewer.md"
        text = md.read_text()
        self.assertIn("name: reviewer", text)
        self.assertIn("description: Reviews code", text)

    def test_refuses_duplicate(self):
        write_subagent(self.repo, "reviewer")
        result = add_subagent(
            name="reviewer", description="x", body="y", repo_path=str(self.repo)
        )
        self.assertFalse(result["ok"])


class RemoveSubagentTestCase(TmpRepoTestCase):
    def test_removes(self):
        write_subagent(self.repo, "reviewer")
        result = remove_subagent("reviewer", repo_path=str(self.repo))
        self.assertTrue(result["ok"])
        self.assertFalse(
            (self.repo / "shared" / "subagents" / "reviewer.md").exists()
        )

    def test_missing(self):
        result = remove_subagent("nope", repo_path=str(self.repo))
        self.assertFalse(result["ok"])


class RepoNotFoundTestCase(TmpRepoTestCase):
    def test_each_function_handles_missing_repo(self):
        bogus = str(self.tmp_path / "missing")
        for fn, args in [
            (add_skill, dict(name="x", description="x", body="y")),
            (remove_skill, dict(name="x")),
            (add_mcp_server, dict(name="x", url="y")),
            (remove_mcp_server, dict(name="x")),
            (add_command, dict(name="x", description="x", body="y")),
            (remove_command, dict(name="x")),
            (add_subagent, dict(name="x", description="x", body="y")),
            (remove_subagent, dict(name="x")),
        ]:
            r = fn(**args, repo_path=bogus)
            self.assertFalse(r["ok"], msg=f"{fn.__name__} did not fail")
            self.assertEqual(r["error"], "agents repo not found")


if __name__ == "__main__":
    unittest.main()
