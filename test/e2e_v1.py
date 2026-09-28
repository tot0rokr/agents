#!/usr/bin/env python3
"""End-to-end check of integrated-harness-kit-mcp v1 on a fresh machine.

Run inside the container built from test/Dockerfile:

    docker run --rm -v "$PWD:/src:ro" agents-test bash -lc \
        'cp -r /src /home/agent/source && python3 /home/agent/source/test/e2e_v1.py'

It does what a person with a new laptop would do — bootstrap the harness, add a
private overlay, change settings, render, commit — and asserts the results on
disk rather than trusting the tools' own return values. Nothing here touches a
host path: $HOME is the container's.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

SOURCE = Path(__file__).resolve().parent.parent          # the repo copy we test from
HOME = Path(os.environ.get("HOME", "/home/agent"))
REPO = HOME / "agents"                                    # where bootstrap installs it
OVERLAY_ORIGIN = HOME / "work-overlay-origin"             # stands in for a private remote

# Unique per run, so the final leak scan cannot be satisfied — or tripped — by
# a fixture string that happens to live in the repo's own test files.
RUN_ID = uuid.uuid4().hex[:10]
SECRET = f"kbpw-{RUN_ID}"
INTERNAL_HOST = f"kb-{RUN_ID}.internal"

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    (PASSED if condition else FAILED).append(name)
    mark = "PASS" if condition else "FAIL"
    print(f"  [{mark}] {name}" + (f" — {detail}" if detail and not condition else ""))


def section(title: str) -> None:
    print(f"\n== {title}")


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-c", "user.name=agent", "-c", "user.email=agent@test", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def build_overlay_origin() -> None:
    """A private overlay repo, as an employer's internal host would serve it."""
    (OVERLAY_ORIGIN / "memory").mkdir(parents=True, exist_ok=True)
    (OVERLAY_ORIGIN / "mcp").mkdir(exist_ok=True)
    (OVERLAY_ORIGIN / "settings").mkdir(exist_ok=True)

    (OVERLAY_ORIGIN / "overlay.json").write_text(
        json.dumps(
            {
                "name": "work",
                "priority": 60,
                "description": "internal environment",
                "claims": {"paths": [str(HOME / "internal-project")]},
                "setup": [
                    {
                        "id": "marker",
                        "description": "a deterministic setup step",
                        "check": f"test -f {HOME}/.work-ready",
                        "run": f"touch {HOME}/.work-ready",
                    }
                ],
            },
            indent=2,
        )
        + "\n"
    )
    (OVERLAY_ORIGIN / "memory" / "internal_host.md").write_text(
        f"---\nname: internal_host\ndescription: internal mount host\n---\n\n{INTERNAL_HOST}\n"
    )
    (OVERLAY_ORIGIN / "memory" / "MEMORY.md").write_text(
        "- [internal_host](internal_host.md) — internal mount host\n"
    )
    (OVERLAY_ORIGIN / "settings" / "claude.json").write_text(
        json.dumps({"autoMode": {"environment": ["internal host list"]}}, indent=2) + "\n"
    )
    (OVERLAY_ORIGIN / "mcp" / "servers.json").write_text(
        json.dumps(
            {
                "servers": {
                    "internal-kb": {
                        "description": "internal knowledge base",
                        "command": "/opt/kb-serve",
                        "args": [],
                        "env": {"KB_PASSWORD": SECRET, "KB_HOST": INTERNAL_HOST},
                    }
                }
            },
            indent=2,
        )
        + "\n"
    )
    git(OVERLAY_ORIGIN, "init", "-q", "-b", "main")
    git(OVERLAY_ORIGIN, "add", "-A")
    git(OVERLAY_ORIGIN, "commit", "-qm", "initial overlay")


def main() -> int:
    sys.path.insert(0, str(SOURCE / "mcp" / "src"))
    from integrated_harness_kit_mcp.tools import (  # noqa: PLC0415
        bootstrap as bootstrap_mod,
        content,
        listing,
        maintenance,
        mcp_servers,
        overlay,
        render as render_mod,
        settings,
        status as status_mod,
    )

    section("1. bootstrap a fresh machine")
    result = bootstrap_mod.bootstrap(dest=str(REPO), repo_url=str(SOURCE), home=str(HOME))
    steps = {step["step"]: step for step in result["steps"]}
    check("bootstrap ok", result["ok"], json.dumps(steps.get("verify", {}))[:400])
    check("repo cloned", (REPO / "scripts" / "install.py").is_file())
    for name in (".claude", ".codex", ".gemini", ".agents"):
        check(f"{name} is a symlink into the repo", (HOME / name).is_symlink())
    for rel in ("claude/settings.json", "shared/mcp/servers.json", "shared/memory/MEMORY.md"):
        check(f"{rel} rendered", (REPO / rel).is_file())
    check("doctor passed", steps["verify"]["doctor"]["ok"])

    section("2. capabilities and status")
    caps = status_mod.capabilities(repo_path=str(REPO))
    check("overlays supported", caps["overlays"])
    check("render_settings available", caps["render_settings"])
    check("version is 1.0.0", caps["package_version"] == "1.0.0", caps["package_version"])

    section("3. add a private overlay")
    build_overlay_origin()
    added = overlay.overlay_add("work", url=str(OVERLAY_ORIGIN), priority=60, repo_path=str(REPO))
    check("overlay_add ok", added["ok"], added.get("stderr", "")[:200])
    installed = overlay.overlay_install("work", repo_path=str(REPO))
    check("overlay_install ok", installed["ok"], installed.get("stderr", "")[:200])
    check(
        "overlay memory is linked in",
        (REPO / "shared" / "memory" / "internal_host.md").is_symlink(),
    )
    live_settings = json.loads((REPO / "claude" / "settings.json").read_text())
    check("overlay settings merged", "autoMode" in live_settings)
    effective = json.loads((REPO / "shared" / "mcp" / "servers.json").read_text())["servers"]
    check("overlay server in the effective set", "internal-kb" in effective)

    section("4. provenance and credential withholding")
    mem = {e["name"]: e["source"] for e in listing.list_content("memory", repo_path=str(REPO))["entries"]}
    check(
        "overlay memory attributed to 'work'",
        mem.get("internal_host") == {"kind": "overlay", "alias": "work"},
        str(mem.get("internal_host")),
    )
    servers = listing.list_mcp_servers(scope="both", repo_path=str(REPO))
    check("overlay_only lists the internal server", servers["overlay_only"] == ["internal-kb"])
    check("base scope excludes it", [e["name"] for e in servers["base"]] == ["linear"])
    check("no credential in the payload", SECRET not in json.dumps(servers))
    entry = next(e for e in servers["effective"] if e["name"] == "internal-kb")
    check("credentials reported as withheld", entry.get("withheld") == ["env"])

    section("5. settings provenance and writes")
    got = settings.settings_get("autoMode", repo_path=str(REPO))
    check("autoMode attributed to the overlay", got["from"] == "overlay:work", str(got))
    base_set = settings.settings_set("theme", "dark", target="base", repo_path=str(REPO))
    check("settings_set base ok", base_set["ok"], json.dumps(base_set)[:200])
    check(
        "theme reached the rendered file",
        json.loads((REPO / "claude" / "settings.json").read_text()).get("theme") == "dark",
    )
    check(
        "runtime-only key refused on base",
        not settings.settings_set("autoMode", {}, target="base", repo_path=str(REPO))["ok"],
    )

    section("6. mcp server writes")
    leaky = mcp_servers.mcp_server_set(
        "leaky", command="/bin/true", env={"T": "x"}, repo_path=str(REPO)
    )
    check("credentials refused on the public base", not leaky["ok"], str(leaky))
    added_server = mcp_servers.mcp_server_set(
        "extra", url="https://example.invalid/mcp", repo_path=str(REPO)
    )
    check("base server added", added_server["ok"], json.dumps(added_server)[:200])
    base_file = json.loads((REPO / "shared" / "mcp" / "servers.base.json").read_text())["servers"]
    check("written to servers.base.json", "extra" in base_file)
    check(
        "overlay server survived the render",
        "internal-kb" in json.loads((REPO / "shared" / "mcp" / "servers.json").read_text())["servers"],
    )

    section("7. render scopes")
    public = render_mod.render(scope="public", repo_path=str(REPO))
    codex = (REPO / "codex" / "config.toml").read_text()
    check("public render ok", public["ok"], json.dumps(public)[:400])
    check("internal server kept out of the tracked config", "internal-kb" not in codex)
    check("base server present in the tracked config", "linear" in codex)
    check(
        "effective servers restored after the swap",
        "internal-kb" in json.loads((REPO / "shared" / "mcp" / "servers.json").read_text())["servers"],
    )

    claude_json = HOME / ".claude.json"
    claude_json.write_text(
        json.dumps(
            {
                "keepMe": True,
                "mcpServers": {
                    "internal-kb": {"command": "/opt/kb-serve", "env": {"KB_PASSWORD": "local-only"}}
                },
            },
            indent=2,
        )
        + "\n"
    )
    local = render_mod.render(scope="local", repo_path=str(REPO), home=str(HOME))
    live = json.loads(claude_json.read_text())
    check("local render ok", local["ok"], json.dumps(local)[:300])
    check("unrelated keys preserved", live.get("keepMe") is True)
    check(
        "overlay env applied",
        live["mcpServers"]["internal-kb"]["env"].get("KB_HOST") == INTERNAL_HOST,
    )
    check(
        "a value only this machine had is not overwritten by a shared one",
        live["mcpServers"]["internal-kb"]["env"].get("KB_PASSWORD") == SECRET,
        str(live["mcpServers"]["internal-kb"]["env"]),
    )

    section("8. routing")
    (HOME / "internal-project").mkdir(exist_ok=True)
    routed = overlay.overlay_route(str(HOME / "internal-project"), repo_path=str(REPO))
    check("claimed path routes to the overlay", routed.get("alias") == "work", str(routed))

    section("9. scaffold into base and overlay")
    base_skill = content.scaffold(
        "skills", "container-skill", description="made in the container", repo_path=str(REPO)
    )
    check("scaffold base skill", base_skill["ok"], json.dumps(base_skill)[:200])
    check(
        "skill file exists",
        (REPO / "universal" / "skills" / "container-skill" / "SKILL.md").is_file(),
    )
    overlay_memory = content.scaffold(
        "memory",
        "container_fact",
        description="internal fact",
        target="overlay:work",
        repo_path=str(REPO),
    )
    check("scaffold into the overlay", overlay_memory["ok"], json.dumps(overlay_memory)[:200])
    check(
        "overlay file linked back in",
        (REPO / "shared" / "memory" / "container_fact.md").is_symlink(),
    )
    check(
        "memory index carries the new line",
        "container_fact" in (REPO / "shared" / "memory" / "MEMORY.md").read_text(),
    )
    check(
        "a name the overlay owns cannot be scaffolded in base",
        not content.scaffold("memory", "container_fact", repo_path=str(REPO))["ok"],
    )

    section("10. setup steps")
    dry = overlay.overlay_setup("work", repo_path=str(REPO))
    check("setup defaults to a dry run", not (HOME / ".work-ready").exists(), dry.get("stdout", "")[:200])
    wet = overlay.overlay_setup("work", yes=True, repo_path=str(REPO))
    check("setup --yes runs the step", (HOME / ".work-ready").exists(), wet.get("stdout", "")[:300])

    section("11. drift and commits")
    git(REPO, "add", "-A")
    git(REPO, "commit", "-qm", "container baseline")
    (REPO / "shared" / "commands" / "container-cmd.md").write_text(
        "---\ndescription: made in the container\n---\n\nBody.\n"
    )
    drift = maintenance.audit_drift(repo_path=str(REPO))
    check("new base file is committable", "shared/commands/container-cmd.md" in drift["committable"])
    check(
        "dirty overlay reported",
        any(o["alias"] == "work" for o in drift["overlays"]),
        json.dumps(drift["overlays"])[:200],
    )
    refused = maintenance.commit(["claude/settings.json"], "should not work", repo_path=str(REPO))
    check("commit refuses a render artifact", not refused["ok"], json.dumps(refused)[:200])
    refused_overlay = maintenance.commit(
        ["shared/memory/internal_host.md"], "should not work", repo_path=str(REPO)
    )
    check("commit refuses an overlay-owned path", not refused_overlay["ok"])
    good = maintenance.commit(
        ["shared/commands/container-cmd.md"], "add a command", repo_path=str(REPO)
    )
    check("commit accepts a base source file", good["ok"], json.dumps(good)[:300])
    overlay_commit = overlay.overlay_commit("work", "add a memory", repo_path=str(REPO))
    check("overlay_commit works in the overlay repo", overlay_commit["ok"], json.dumps(overlay_commit)[:300])

    section("12. update")
    updated = maintenance.update(with_pull=False, repo_path=str(REPO))
    check("update ok", updated["ok"], json.dumps([s["step"] for s in updated["steps"]]))

    section("13. the public repo carries no overlay content")
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=str(REPO), capture_output=True, text=True
    ).stdout.split()
    leaked = []
    for rel in tracked:
        path = REPO / rel
        if not path.is_file() or path.is_symlink():
            continue
        try:
            text = path.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        if SECRET in text or INTERNAL_HOST in text:
            leaked.append(rel)
    check("no tracked file contains overlay secrets or hosts", not leaked, str(leaked))

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        print("failed: " + ", ".join(FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
