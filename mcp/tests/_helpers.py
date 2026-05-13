"""Shared test fixtures for harness-adapter-mcp.

Each test creates a self-contained fake repo under a TemporaryDirectory so
nothing touches the developer's real `~/agents` or `~/.claude`.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


def make_fake_repo(root: Path) -> Path:
    """Build the smallest repo layout that `repo.find_repo` accepts."""
    repo = root / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "scripts" / "install.py").write_text("# placeholder\n")
    # The five symlink targets.
    for sub in ("claude", "codex", "opencode", "gemini", "universal"):
        (repo / sub).mkdir()
    # Canonical content roots.
    (repo / "universal" / "skills").mkdir()
    (repo / "shared" / "memory").mkdir(parents=True)
    (repo / "shared" / "mcp").mkdir()
    (repo / "shared" / "subagents").mkdir()
    (repo / "shared" / "commands").mkdir()
    return repo


def make_fake_home(root: Path) -> Path:
    home = root / "home"
    home.mkdir()
    return home


def install_doctor_stub(repo: Path, body: str = '#!/usr/bin/env bash\necho "doctor: all checks passed"\nexit 0\n') -> None:
    """Drop a minimal doctor.sh that the doctor tool can shell out to."""
    script = repo / "scripts" / "doctor.sh"
    script.write_text(body)
    script.chmod(0o755)


def write_skill(repo: Path, name: str, description: str = "test skill", body: str = "Body.\n") -> Path:
    d = repo / "universal" / "skills" / name
    d.mkdir(parents=True)
    skill = d / "SKILL.md"
    skill.write_text(f"---\nname: {name}\ndescription: {description}\n---\n\n{body}")
    return skill


def write_subagent(repo: Path, name: str, description: str = "test sub-agent", body: str = "Body.\n") -> Path:
    f = repo / "shared" / "subagents" / f"{name}.md"
    f.write_text(f"---\nname: {name}\ndescription: {description}\n---\n\n{body}")
    return f


def write_command(repo: Path, name: str, description: str = "test command", body: str = "Body.\n") -> Path:
    f = repo / "shared" / "commands" / f"{name}.md"
    f.write_text(f"---\ndescription: {description}\n---\n\n{body}")
    return f


def write_mcp_servers(repo: Path, servers: dict) -> Path:
    f = repo / "shared" / "mcp" / "servers.json"
    f.write_text(json.dumps({"servers": servers}, indent=2))
    return f


class TmpRepoTestCase(unittest.TestCase):
    """Base class providing a fake repo + home in a TemporaryDirectory."""

    def setUp(self) -> None:
        # Ensure src/ is importable. Tests are run from `mcp/` directory.
        src_path = Path(__file__).resolve().parent.parent / "src"
        if str(src_path) not in sys.path:
            sys.path.insert(0, str(src_path))

        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self.repo = make_fake_repo(self.tmp_path)
        self.home = make_fake_home(self.tmp_path)

    def tearDown(self) -> None:
        self._tmp.cleanup()
