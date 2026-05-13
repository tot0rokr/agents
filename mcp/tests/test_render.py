"""Tests for the render tool."""

from __future__ import annotations

import unittest

from tests._helpers import TmpRepoTestCase
from integrated_harness_kit_mcp.tools.render import render


def _install_render_stub(repo, name, body=None):
    body = body or '#!/usr/bin/env bash\necho "rendered {}"\nexit 0\n'.format(name)
    s = repo / "scripts" / name
    s.write_text(body)
    s.chmod(0o755)


class RenderTestCase(TmpRepoTestCase):
    def test_unknown_kind(self):
        result = render(kind="bogus", repo_path=str(self.repo))
        self.assertFalse(result["ok"])
        self.assertIn("unknown kind", result["error"])

    def test_repo_missing(self):
        result = render(repo_path=str(self.tmp_path / "nope"))
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "agents repo not found")

    def test_mcp_only(self):
        _install_render_stub(self.repo, "render-mcp.sh")
        result = render(kind="mcp", repo_path=str(self.repo))
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["scripts"]), 1)
        self.assertEqual(result["scripts"][0]["name"], "render-mcp.sh")
        self.assertEqual(result["scripts"][0]["exit_code"], 0)

    def test_all_with_one_missing_script(self):
        _install_render_stub(self.repo, "render-mcp.sh")
        # render-gemini-commands.sh not installed.
        result = render(kind="all", repo_path=str(self.repo))
        self.assertFalse(result["ok"])
        names = {s["name"]: s for s in result["scripts"]}
        self.assertEqual(names["render-mcp.sh"]["exit_code"], 0)
        self.assertEqual(names["render-gemini-commands.sh"]["exit_code"], -1)

    def test_failing_render(self):
        _install_render_stub(
            self.repo,
            "render-mcp.sh",
            body='#!/usr/bin/env bash\necho "boom" >&2\nexit 5\n',
        )
        result = render(kind="mcp", repo_path=str(self.repo))
        self.assertFalse(result["ok"])
        self.assertEqual(result["scripts"][0]["exit_code"], 5)
        self.assertIn("boom", result["scripts"][0]["stderr"])


if __name__ == "__main__":
    unittest.main()
