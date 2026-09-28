"""Shared test fixtures for integrated-harness-kit-mcp.

Each test builds a self-contained fake repo under a TemporaryDirectory, so
nothing touches the developer's real `~/agents` or `~/.claude`.

The fake repo can carry the harness's *real* `scripts/` (install.py,
render_settings.py, overlay.py). That makes the overlay and render tests
functional rather than mocked: they exercise the same code the machine runs.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REAL_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
COPIED_SCRIPTS = ("install.py", "render_settings.py", "overlay.py")


def make_fake_repo(root: Path, with_scripts: bool = False, git_init: bool = False) -> Path:
    """Build the smallest repo layout that `repo.find_repo` accepts."""
    repo = root / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "scripts" / "install.py").write_text("# placeholder\n")
    for sub in ("claude", "codex", "opencode", "gemini", "universal"):
        (repo / sub).mkdir()
    (repo / "universal" / "skills").mkdir()
    (repo / "shared" / "memory").mkdir(parents=True)
    (repo / "shared" / "mcp").mkdir()
    (repo / "shared" / "subagents").mkdir()
    (repo / "shared" / "commands").mkdir()
    (repo / "shared" / "instructions").mkdir()

    if with_scripts:
        for name in COPIED_SCRIPTS:
            source = REAL_SCRIPTS / name
            if source.is_file():
                shutil.copyfile(source, repo / "scripts" / name)
        (repo / "templates").mkdir(exist_ok=True)
        template = REAL_SCRIPTS.parent / "templates" / "overlay-example"
        if template.is_dir():
            shutil.copytree(template, repo / "templates" / "overlay-example")

    if git_init:
        _git(repo, "init", "-q", "-b", "main")

    return repo


def write_bases(repo: Path, model: str = "test-model", servers: dict | None = None) -> None:
    """The tracked sources the renderers read."""
    (repo / "claude" / "settings.base.json").write_text(
        json.dumps({"model": model, "env": {"KEEP": "base"}}, indent=2) + "\n"
    )
    (repo / "shared" / "mcp" / "servers.base.json").write_text(
        json.dumps({"servers": servers if servers is not None else {"linear": {"url": "https://mcp.linear.app/mcp", "transport": "http"}}}, indent=2)
        + "\n"
    )
    (repo / "shared" / "memory" / "MEMORY.base.md").write_text("- [base note](base_note.md) — public\n")


def make_overlay(
    repo: Path,
    alias: str,
    priority: int = 50,
    memories: dict[str, str] | None = None,
    settings: dict | None = None,
    servers: dict | None = None,
    index_lines: list[str] | None = None,
    manifest_extra: dict | None = None,
) -> Path:
    """Create and commit an overlay clone at overlays/<alias>."""
    root = repo / "overlays" / alias
    (root / "memory").mkdir(parents=True, exist_ok=True)

    manifest = {"name": alias, "priority": priority, "description": f"{alias} overlay"}
    manifest.update(manifest_extra or {})
    (root / "overlay.json").write_text(json.dumps(manifest, indent=2) + "\n")

    for name, text in (memories or {}).items():
        (root / "memory" / f"{name}.md").write_text(text)
    if index_lines:
        (root / "memory" / "MEMORY.md").write_text("\n".join(index_lines) + "\n")
    if settings is not None:
        (root / "settings").mkdir(exist_ok=True)
        (root / "settings" / "claude.json").write_text(json.dumps(settings, indent=2) + "\n")
    if servers is not None:
        (root / "mcp").mkdir(exist_ok=True)
        (root / "mcp" / "servers.json").write_text(json.dumps({"servers": servers}, indent=2) + "\n")

    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@e", "commit", "-qm", "overlay")
    return root


def overlay_cli(repo: Path, *args: str) -> subprocess.CompletedProcess:
    """Run the repo's own scripts/overlay.py the way a user would."""
    return subprocess.run(
        [sys.executable, str(repo / "scripts" / "overlay.py"), *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=120,
    )


def register_and_install(repo: Path, alias: str, priority: int = 50) -> subprocess.CompletedProcess:
    overlay_cli(repo, "add", alias, "--priority", str(priority))
    return overlay_cli(repo, "install", alias)


def make_fake_home(root: Path) -> Path:
    home = root / "home"
    home.mkdir()
    return home


def write_claude_json(home: Path, servers: dict) -> Path:
    path = home / ".claude.json"
    path.write_text(json.dumps({"other": "keep", "mcpServers": servers}, indent=2) + "\n")
    path.chmod(0o600)
    return path


def install_doctor_stub(
    repo: Path,
    body: str = '#!/usr/bin/env bash\necho "doctor: all checks passed"\nexit 0\n',
) -> None:
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


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)


class TmpRepoTestCase(unittest.TestCase):
    """Fake repo + home in a TemporaryDirectory."""

    with_scripts = False
    git_init = False

    def setUp(self) -> None:
        src_path = Path(__file__).resolve().parent.parent / "src"
        if str(src_path) not in sys.path:
            sys.path.insert(0, str(src_path))

        from integrated_harness_kit_mcp import repo_scripts  # noqa: PLC0415

        repo_scripts.clear_cache()

        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self.repo = make_fake_repo(
            self.tmp_path, with_scripts=self.with_scripts, git_init=self.git_init
        )
        self.home = make_fake_home(self.tmp_path)

    def tearDown(self) -> None:
        self._tmp.cleanup()


class HarnessTestCase(TmpRepoTestCase):
    """A fake repo carrying the real scripts, as a git repo, with base files."""

    with_scripts = True
    git_init = True

    def setUp(self) -> None:
        super().setUp()
        write_bases(self.repo)
