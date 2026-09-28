#!/usr/bin/env python3
"""Adversarial QA pass over integrated-harness-kit-mcp v1.

`e2e_v1.py` walks the happy path. This one tries to break it: path traversal,
corrupt state, missing files, unwritable targets, malicious overlays, priority
conflicts, idempotence, and every read tool checked for credential leakage.

Run in the container (it chmods files and writes junk on purpose):

    python3 test/qa_v1.py
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import uuid
from pathlib import Path

SOURCE = Path(__file__).resolve().parent.parent
HOME = Path(os.environ.get("HOME", "/home/agent"))
REPO = HOME / "qa-agents"
ORIGINS = HOME / "qa-origins"

RUN_ID = uuid.uuid4().hex[:10]
SECRET = f"qapw-{RUN_ID}"
HOSTNAME = f"kb-{RUN_ID}.internal"

PASSED: list[str] = []
FAILED: list[str] = []
CRASHED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    (PASSED if condition else FAILED).append(name)
    print(f"  [{'PASS' if condition else 'FAIL'}] {name}" + (f" — {detail[:220]}" if detail and not condition else ""))


def survives(name: str, fn, *args, **kwargs):
    """A tool may return an error payload; it may never raise."""
    try:
        result = fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001
        CRASHED.append(name)
        print(f"  [CRASH] {name} — {type(exc).__name__}: {exc}")
        return None
    return result


def section(title: str) -> None:
    print(f"\n== {title}")


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-c", "user.name=qa", "-c", "user.email=qa@test", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def make_overlay_origin(alias: str, priority: int, extra: dict | None = None) -> Path:
    root = ORIGINS / alias
    (root / "memory").mkdir(parents=True, exist_ok=True)
    manifest = {"name": alias, "priority": priority}
    manifest.update(extra or {})
    (root / "overlay.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (root / "memory" / f"{alias}_note.md").write_text(
        f"---\nname: {alias}_note\ndescription: {alias} note\n---\n\n{HOSTNAME}\n"
    )
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "overlay")
    return root


def main() -> int:
    sys.path.insert(0, str(SOURCE / "mcp" / "src"))
    from integrated_harness_kit_mcp import layout  # noqa: PLC0415
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

    R = str(REPO)

    section("0. set up a repo under test")
    shutil.rmtree(REPO, ignore_errors=True)
    shutil.rmtree(ORIGINS, ignore_errors=True)
    boot = bootstrap_mod.bootstrap(dest=R, repo_url=str(SOURCE), home=str(HOME), with_overlays=False)
    check("bootstrap for QA", boot["ok"], json.dumps(boot)[:300])

    work = make_overlay_origin(
        "work",
        60,
        {
            "claims": {"paths": [str(HOME / "wk")]},
            "links": {"memory/work_note.md": "shared/memory/aliased_note.md"},
        },
    )
    (work / "mcp").mkdir(exist_ok=True)
    (work / "mcp" / "servers.json").write_text(
        json.dumps({"servers": {"kb": {"command": "/opt/kb", "env": {"PW": SECRET}}}}, indent=2) + "\n"
    )
    (work / "settings").mkdir(exist_ok=True)
    (work / "settings" / "claude.json").write_text(json.dumps({"model": "work-model"}, indent=2) + "\n")
    git(work, "add", "-A")
    git(work, "commit", "-qm", "content")
    overlay.overlay_add("work", url=str(work), priority=60, repo_path=R)
    overlay.overlay_install("work", repo_path=R)

    # ------------------------------------------------------------------ A
    section("A. path traversal and name validation")
    for bad in ("../escape", "..", "a/b", "/abs", "x" * 200, "", ".."):
        result = survives(f"scaffold({bad!r})", content.scaffold, "memory", bad, repo_path=R)
        if result is not None:
            check(f"scaffold refuses name {bad!r}", not result.get("ok"), json.dumps(result)[:150])
    check(
        "no file escaped the repo",
        not (HOME / "escape.md").exists() and not Path("/tmp/escape.md").exists(),
    )

    trav = survives("commit(../)", maintenance.commit, ["../outside.txt"], "nope", repo_path=R)
    if trav is not None:
        check("commit refuses a traversing path", not trav.get("ok"), json.dumps(trav)[:150])

    oc = survives(
        "overlay_commit(../)",
        overlay.overlay_commit,
        "work",
        "nope",
        paths=["../../shared"],
        repo_path=R,
    )
    if oc is not None:
        check("overlay_commit refuses a traversing path", not oc.get("ok"), json.dumps(oc)[:150])

    for bad_name in ("../evil", "a b", "sp ace"):
        result = survives(
            f"mcp_server_set({bad_name!r})",
            mcp_servers.mcp_server_set,
            bad_name,
            url="https://x.invalid",
            repo_path=R,
        )
        if result is not None:
            written = json.loads((REPO / "shared/mcp/servers.base.json").read_text())["servers"]
            check(
                f"server name {bad_name!r} cannot create a path",
                "../" not in json.dumps(written),
                json.dumps(written)[:150],
            )

    # ------------------------------------------------------------------ B
    section("B. credential containment across every read tool")
    payloads = {
        "list_mcp_servers/effective": listing.list_mcp_servers(scope="effective", repo_path=R),
        "list_mcp_servers/both": listing.list_mcp_servers(scope="both", repo_path=R),
        "list_content/memory": listing.list_content("memory", repo_path=R),
        "status/full": status_mod.status(level="full", repo_path=R, home=str(HOME)),
        "settings_get": settings.settings_get(repo_path=R),
        "overlay_list": overlay.overlay_list(repo_path=R),
        "audit_drift": maintenance.audit_drift(repo_path=R),
        "capabilities": status_mod.capabilities(repo_path=R),
    }
    for name, payload in payloads.items():
        check(f"{name} withholds the password", SECRET not in json.dumps(payload))

    # ------------------------------------------------------------------ C
    section("C. corrupt and missing state")
    corruptions = {
        "claude/settings.base.json": "{not json",
        "shared/mcp/servers.base.json": "",
        "overlays/registry.local.json": "[]",
        "overlays/applied.local.json": "{}",
        "overlays/work/overlay.json": "{oops",
    }
    for rel, junk in corruptions.items():
        path = REPO / rel
        backup = path.read_text() if path.is_file() else None
        path.write_text(junk)
        for tool_name, fn, args in (
            ("status", status_mod.status, ()),
            ("settings_get", settings.settings_get, ()),
            ("list_mcp_servers", listing.list_mcp_servers, ()),
            ("audit_drift", maintenance.audit_drift, ()),
            ("overlay_list", overlay.overlay_list, ()),
        ):
            survives(f"{tool_name} with corrupt {rel}", fn, *args, repo_path=R)
        rendered = survives(f"render with corrupt {rel}", render_mod.render, "artifacts", repo_path=R)
        if rendered is not None and rel.endswith("settings.base.json"):
            check("render reports a broken base instead of crashing", not rendered["ok"])
        if backup is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(backup)
    check("no tool raised on corrupt state", not CRASHED, str(CRASHED))

    render_mod.render(scope="artifacts", repo_path=R)

    section("C2. registered overlay whose clone is gone")
    shutil.move(str(REPO / "overlays" / "work"), str(HOME / "work-moved"))
    for name, fn in (
        ("status", status_mod.status),
        ("overlay_list", overlay.overlay_list),
        ("settings_get", settings.settings_get),
        ("audit_drift", maintenance.audit_drift),
    ):
        result = survives(f"{name} with a missing clone", fn, repo_path=R)
        if result is not None and name == "overlay_list":
            entry = next(e for e in result["overlays"] if e["alias"] == "work")
            check("missing clone reported as not cloned", entry["cloned"] is False)
    dangling = REPO / "shared" / "memory" / "work_note.md"
    check("link is now dangling", dangling.is_symlink() and not dangling.exists())
    listed = survives("list_content over a dangling link", listing.list_content, "memory", repo_path=R)
    check("listing survives a dangling link", listed is not None and listed.get("ok"))
    shutil.move(str(HOME / "work-moved"), str(REPO / "overlays" / "work"))
    overlay.overlay_install("work", repo_path=R)

    # ------------------------------------------------------------------ D
    section("D. unwritable targets")
    base = REPO / "claude" / "settings.base.json"
    mode = base.stat().st_mode
    base.chmod(stat.S_IRUSR)
    result = survives("settings_set on a read-only base", settings.settings_set, "theme", "x", repo_path=R)
    if result is not None:
        check("read-only base is an error, not a crash", not result.get("ok"), json.dumps(result)[:200])
    base.chmod(mode)

    # ------------------------------------------------------------------ E
    section("E. a hostile overlay")
    evil = make_overlay_origin(
        "evil",
        70,
        {"links": {"memory/evil_note.md": "../../../../tmp/pwned.md"}},
    )
    overlay.overlay_add("evil", url=str(evil), priority=70, repo_path=R)
    installed = survives("install a traversing links map", overlay.overlay_install, "evil", repo_path=R)
    check(
        "a links target outside the repo does not land there",
        not Path("/tmp/pwned.md").exists(),
        str(installed)[:200],
    )
    overlay.overlay_remove("evil", purge=True, repo_path=R)
    Path("/tmp/pwned.md").unlink(missing_ok=True)

    section("E2. setup steps never run implicitly")
    marker = HOME / ".qa-should-not-exist"
    manifest = REPO / "overlays" / "work" / "overlay.json"
    data = json.loads(manifest.read_text())
    data["setup"] = [{"id": "danger", "check": f"test -f {marker}", "run": f"touch {marker}"}]
    manifest.write_text(json.dumps(data, indent=2))
    for name, fn, kwargs in (
        ("overlay_install", overlay.overlay_install, {"alias": "work"}),
        ("update", maintenance.update, {"with_pull": False}),
        ("status/full", status_mod.status, {"level": "full", "home": str(HOME)}),
        ("audit_drift", maintenance.audit_drift, {}),
        ("overlay_setup dry", overlay.overlay_setup, {"alias": "work"}),
    ):
        survives(name, fn, repo_path=R, **kwargs)
        check(f"{name} did not execute the setup step", not marker.exists())
    overlay.overlay_setup("work", yes=True, repo_path=R)
    check("overlay_setup(yes=True) does execute it", marker.exists())
    marker.unlink(missing_ok=True)

    # ------------------------------------------------------------------ F
    section("F. priority, conflicts, idempotence")
    low = make_overlay_origin("low", 10, {})
    (low / "settings").mkdir(exist_ok=True)
    (low / "settings" / "claude.json").write_text(json.dumps({"model": "low-model", "onlyLow": 1}) + "\n")
    git(low, "add", "-A")
    git(low, "commit", "-qm", "settings")
    overlay.overlay_add("low", url=str(low), priority=10, repo_path=R)
    overlay.overlay_install(repo_path=R)

    live = json.loads((REPO / "claude" / "settings.json").read_text())
    check("higher priority wins a shared key", live.get("model") == "work-model", str(live.get("model")))
    check("lower priority still contributes its own keys", live.get("onlyLow") == 1)
    check(
        "provenance names the winner",
        settings.settings_get("model", repo_path=R)["from"] == "overlay:work",
    )

    collide = make_overlay_origin("collide", 80, {})
    shutil.copyfile(
        REPO / "overlays" / "work" / "memory" / "work_note.md",
        collide / "memory" / "work_note.md",
    )
    git(collide, "add", "-A")
    git(collide, "commit", "-qm", "collide")
    overlay.overlay_add("collide", url=str(collide), priority=80, repo_path=R)
    conflict = survives("install a colliding overlay", overlay.overlay_install, "collide", repo_path=R)
    check("a name two overlays supply is refused", conflict is not None and not conflict["ok"], str(conflict)[:200])
    check(
        "the original link is untouched after the refusal",
        (REPO / "shared" / "memory" / "work_note.md").resolve().parent.name == "memory"
        and "work" in str((REPO / "shared" / "memory" / "work_note.md").resolve()),
    )
    overlay.overlay_remove("collide", purge=True, repo_path=R)

    first = (REPO / "claude" / "settings.json").read_text()
    render_mod.render(scope="artifacts", repo_path=R)
    render_mod.render(scope="artifacts", repo_path=R)
    check("render is byte-identical when repeated", (REPO / "claude" / "settings.json").read_text() == first)

    overlay.overlay_install(repo_path=R)
    overlay.overlay_install(repo_path=R)
    check("install is idempotent", overlay.overlay_list(repo_path=R)["ok"])
    check(
        "aliased link from the manifest exists",
        (REPO / "shared" / "memory" / "aliased_note.md").is_symlink(),
    )

    # ------------------------------------------------------------------ G
    section("G. removal is complete")
    before_keys = set(json.loads((REPO / "claude" / "settings.json").read_text()))
    live = json.loads((REPO / "claude" / "settings.json").read_text())
    live["runtimeOnly"] = {"keep": True}
    (REPO / "claude" / "settings.json").write_text(json.dumps(live, indent=2) + "\n")

    overlay.overlay_remove("low", purge=True, repo_path=R)
    after = json.loads((REPO / "claude" / "settings.json").read_text())
    check("a removed overlay's key is gone", "onlyLow" not in after)
    check("runtime state survives the removal", after.get("runtimeOnly") == {"keep": True})
    check("other overlays keep their keys", after.get("model") == "work-model")
    check("no key vanished that nobody owned", before_keys - {"onlyLow"} <= set(after))

    # ------------------------------------------------------------------ H
    section("H. a repo from before overlays")
    legacy = HOME / "legacy-repo"
    shutil.rmtree(legacy, ignore_errors=True)
    shutil.copytree(REPO, legacy, symlinks=True)
    for rel in ("scripts/overlay.py", "scripts/render_settings.py", "overlays"):
        target = legacy / rel
        shutil.rmtree(target, ignore_errors=True) if target.is_dir() else target.unlink(missing_ok=True)
    from integrated_harness_kit_mcp import repo_scripts  # noqa: PLC0415

    repo_scripts.clear_cache()
    caps = survives("capabilities on a legacy repo", status_mod.capabilities, repo_path=str(legacy))
    check("overlays reported unsupported", caps is not None and not caps["overlays"])
    for name, fn, args in (
        ("status", status_mod.status, ()),
        ("list_content", listing.list_content, ("memory",)),
        ("audit_drift", maintenance.audit_drift, ()),
        ("settings_get", settings.settings_get, ()),
        ("overlay_list", overlay.overlay_list, ()),
        ("render", render_mod.render, ("artifacts",)),
    ):
        result = survives(f"{name} on a legacy repo", fn, *args, repo_path=str(legacy))
        check(f"{name} degrades without raising", result is not None)
    repo_scripts.clear_cache()

    # ------------------------------------------------------------------ I
    section("I. unicode and awkward content")
    uni = survives(
        "scaffold with unicode description",
        content.scaffold,
        "memory",
        "unicode_note",
        description="한국어 설명 — em dash, quotes \"x\"",
        repo_path=R,
    )
    check("unicode description accepted", uni is not None and uni.get("ok"), json.dumps(uni)[:200])
    check(
        "unicode survives the round trip",
        "한국어" in (REPO / "shared" / "memory" / "unicode_note.md").read_text(),
    )
    settings.settings_set("statusLine.command", 'bash "$HOME/x.sh" --flag', target="base", repo_path=R)
    check(
        "a value with quotes and $ survives rendering",
        json.loads((REPO / "claude" / "settings.json").read_text())["statusLine"]["command"]
        == 'bash "$HOME/x.sh" --flag',
    )

    # ------------------------------------------------------------------ J
    section("J. not a git repo")
    nogit = HOME / "nogit-repo"
    shutil.rmtree(nogit, ignore_errors=True)
    shutil.copytree(REPO, nogit, symlinks=True)
    shutil.rmtree(nogit / ".git", ignore_errors=True)
    drift = survives("audit_drift without .git", maintenance.audit_drift, repo_path=str(nogit))
    check("audit_drift reports the git failure", drift is not None and not drift.get("ok"), json.dumps(drift)[:200])
    committed = survives(
        "commit without .git", maintenance.commit, ["shared/AGENTS.md"], "x", repo_path=str(nogit)
    )
    check("commit fails cleanly without git", committed is not None and not committed.get("ok"))

    section("K. render-mcp.sh is safe to run by hand")
    # Someone will run the script directly, without the MCP package's scopes.
    # It must still keep overlay servers out of the tracked configs and must not
    # wipe a credential that only exists on this machine.
    claude_json = HOME / ".claude.json"
    claude_json.write_text(
        json.dumps(
            {
                "keepMe": True,
                "mcpServers": {
                    # LOCAL_ONLY is defined nowhere else; PW is owned by the
                    # overlay, so the render is supposed to win that one.
                    "kb": {"command": "/opt/kb", "env": {"LOCAL_ONLY": "keep-me", "PW": "stale"}},
                    "hand-registered": {"command": "/bin/true"},
                },
            },
            indent=2,
        )
        + "\n"
    )
    script = REPO / "scripts" / "render-mcp.sh"
    proc = subprocess.run(["bash", str(script)], cwd=str(REPO), capture_output=True, text=True)
    check("render-mcp.sh exits 0", proc.returncode == 0, proc.stderr[-300:])

    for rel in ("codex/config.toml", "gemini/settings.json", "opencode/opencode.json"):
        text = (REPO / rel).read_text()
        check(f"{rel} has no overlay server", "kb" not in text or "linear" in text and '"kb"' not in text, text[:160])
        check(f"{rel} carries no credential", SECRET not in text)

    live = json.loads(claude_json.read_text())
    check("local config keeps unrelated top-level keys", live.get("keepMe") is True)
    check("a hand-registered server is not dropped", "hand-registered" in live["mcpServers"])
    check(
        "a value only this machine has survives the script",
        live["mcpServers"]["kb"]["env"].get("LOCAL_ONLY") == "keep-me",
        json.dumps(live["mcpServers"]["kb"]),
    )
    check(
        "a value the overlay owns is refreshed from it",
        live["mcpServers"]["kb"]["env"].get("PW") == SECRET,
        json.dumps(live["mcpServers"]["kb"]),
    )

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed, {len(CRASHED)} crashed")
    if FAILED:
        print("failed: " + "; ".join(FAILED))
    if CRASHED:
        print("crashed: " + "; ".join(CRASHED))
    return 1 if FAILED or CRASHED else 0


if __name__ == "__main__":
    sys.exit(main())
