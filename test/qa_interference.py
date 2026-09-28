#!/usr/bin/env python3
"""Does applying an overlay ever drop a setting that was already there?

Each case sets up a concrete "before", applies or removes an overlay, and
reports what happened to every key — rather than asserting what should happen.
Cases are labelled `by design` or `LOSS` so the ones that need fixing stand out.

Run in the container:  python3 test/qa_interference.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SOURCE = Path(__file__).resolve().parent.parent
HOME = Path(os.environ.get("HOME", "/home/agent"))
REPO = HOME / "interference-repo"
ORIGINS = HOME / "interference-origins"

FINDINGS: list[tuple[str, str, str]] = []  # (verdict, case, detail)


def record(verdict: str, case: str, detail: str = "") -> None:
    FINDINGS.append((verdict, case, detail))
    print(f"  [{verdict}] {case}" + (f" — {detail}" if detail else ""))


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-c", "user.name=qa", "-c", "user.email=qa@test", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def overlay_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO / "scripts" / "overlay.py"), *args],
        cwd=str(REPO),
        capture_output=True,
        text=True,
    )


def make_overlay(alias: str, priority: int, settings: dict | None = None, **extra) -> Path:
    root = ORIGINS / alias
    shutil.rmtree(root, ignore_errors=True)
    (root / "memory").mkdir(parents=True)
    manifest = {"name": alias, "priority": priority}
    manifest.update(extra)
    (root / "overlay.json").write_text(json.dumps(manifest, indent=2) + "\n")
    if settings is not None:
        (root / "settings").mkdir()
        (root / "settings" / "claude.json").write_text(json.dumps(settings, indent=2) + "\n")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-qm", alias)
    return root


def fresh_repo(base_settings: dict) -> None:
    shutil.rmtree(REPO, ignore_errors=True)
    subprocess.run(["git", "clone", "-q", str(SOURCE), str(REPO)], check=True)
    (REPO / "claude" / "settings.base.json").write_text(json.dumps(base_settings, indent=2) + "\n")
    subprocess.run([sys.executable, str(REPO / "scripts" / "render_settings.py")],
                   cwd=str(REPO), capture_output=True)


def live() -> dict:
    return json.loads((REPO / "claude" / "settings.json").read_text())


def main() -> int:
    shutil.rmtree(ORIGINS, ignore_errors=True)
    ORIGINS.mkdir(parents=True)

    print("== 1. an overlay that touches nothing the base defines")
    fresh_repo({"model": "base-model", "theme": "dark", "hooks": {"Stop": [{"id": "base-stop"}]}})
    before = live()
    make_overlay("plain", 60, settings={"newKey": 1})
    overlay_cli("add", "plain", str(ORIGINS / "plain"), "--priority", "60")
    overlay_cli("install", "plain")
    after = live()
    lost = [k for k in before if k not in after]
    changed = [k for k in before if k in after and before[k] != after[k]]
    record("PASS" if not lost and not changed else "LOSS",
           "unrelated base keys survive", f"lost={lost} changed={changed}")
    record("PASS" if after.get("newKey") == 1 else "LOSS",
           "the overlay's own key did land", f"newKey={after.get('newKey')}")

    print("\n== 2. an overlay that sets a key the base already sets")
    record("by design", "the higher-priority source wins",
           f"model={after.get('model')} (base said base-model)")
    fresh_repo({"model": "base-model", "theme": "dark"})
    make_overlay("winner", 60, settings={"model": "overlay-model"})
    overlay_cli("add", "winner", str(ORIGINS / "winner"), "--priority", "60")
    overlay_cli("install", "winner")
    record("by design", "overlay wins the shared key",
           f"model={live().get('model')}, theme kept={live().get('theme')}")

    print("\n== 3. an overlay that defines a list the base also defines")
    fresh_repo({"hooks": {"Stop": [{"id": "base-stop"}], "PreCompact": [{"id": "base-pre"}]}})
    make_overlay("hooky", 60, settings={"hooks": {"Stop": [{"id": "overlay-stop"}]}})
    overlay_cli("add", "hooky", str(ORIGINS / "hooky"), "--priority", "60")
    overlay_cli("install", "hooky")
    hooks = live()["hooks"]
    stop_ids = [h.get("id") for h in hooks.get("Stop", [])]
    record("by design" if "base-stop" not in stop_ids else "PASS",
           "a list is replaced, not concatenated",
           f"Stop={stop_ids}; sibling event kept={[h.get('id') for h in hooks.get('PreCompact', [])]}")

    print("\n== 4. a key Claude Code wrote at runtime")
    fresh_repo({"model": "base-model"})
    make_overlay("rt", 60, settings={"autoMode": {"environment": ["from overlay"]}})
    overlay_cli("add", "rt", str(ORIGINS / "rt"), "--priority", "60")
    overlay_cli("install", "rt")
    current = live()
    current["runtimeFlag"] = {"nested": True}
    current["model"] = "user-changed-at-runtime"
    (REPO / "claude" / "settings.json").write_text(json.dumps(current, indent=2) + "\n")
    subprocess.run([sys.executable, str(REPO / "scripts" / "render_settings.py")],
                   cwd=str(REPO), capture_output=True)
    after = live()
    record("PASS" if after.get("runtimeFlag") == {"nested": True} else "LOSS",
           "a key no source claims survives a render", str(after.get("runtimeFlag")))
    record("by design", "a key the base claims is restored from the base",
           f"model={after.get('model')} (runtime said user-changed-at-runtime)")

    print("\n== 5. removing one overlay while another stays")
    fresh_repo({"model": "base-model"})
    make_overlay("a", 50, settings={"fromA": 1, "shared": "a"})
    make_overlay("b", 60, settings={"fromB": 2, "shared": "b"})
    for alias, prio in (("a", "50"), ("b", "60")):
        overlay_cli("add", alias, str(ORIGINS / alias), "--priority", prio)
    overlay_cli("install")
    both = live()
    overlay_cli("remove", "b")
    after = live()
    record("PASS" if after.get("fromA") == 1 else "LOSS",
           "the remaining overlay keeps its keys", f"fromA={after.get('fromA')}")
    record("PASS" if "fromB" not in after else "LOSS",
           "the removed overlay's keys are gone", f"fromB={after.get('fromB')}")
    record("PASS" if after.get("shared") == "a" else "LOSS",
           "a shared key falls back to the remaining source",
           f"shared={after.get('shared')} (was {both.get('shared')})")
    record("PASS" if after.get("model") == "base-model" else "LOSS",
           "base keys are untouched", f"model={after.get('model')}")

    print("\n== 6. the memory index when someone edits it by hand")
    fresh_repo({"model": "base-model"})
    (REPO / "shared" / "memory" / "MEMORY.base.md").write_text("- [one](one.md) — first\n")
    make_overlay("mem", 60)
    (ORIGINS / "mem" / "memory" / "MEMORY.md").write_text("- [two](two.md) — from the overlay\n")
    git(ORIGINS / "mem", "add", "-A")
    git(ORIGINS / "mem", "commit", "-qm", "index")
    overlay_cli("add", "mem", str(ORIGINS / "mem"), "--priority", "60")
    overlay_cli("install", "mem")
    index = REPO / "shared" / "memory" / "MEMORY.md"
    agent_line = "- [three](three.md) — written by an agent at runtime\n"
    index.write_text(index.read_text() + agent_line)
    subprocess.run([sys.executable, str(REPO / "scripts" / "render_settings.py")],
                   cwd=str(REPO), capture_output=True)
    text = index.read_text()
    record("PASS" if "three.md" in text else "LOSS",
           "a line an agent appended survives a render")
    record("PASS" if text.count("- [one](one.md)") == 1 else "LOSS",
           "base lines are not duplicated", f"count={text.count('- [one](one.md)')}")
    record("PASS" if text.count("- [two](two.md)") == 1 else "LOSS",
           "overlay lines are not duplicated", f"count={text.count('- [two](two.md)')}")

    edited = text.replace("- [one](one.md) — first", "- [one](one.md) — EDITED IN PLACE")
    index.write_text(edited)
    subprocess.run([sys.executable, str(REPO / "scripts" / "render_settings.py")],
                   cwd=str(REPO), capture_output=True)
    text = index.read_text()
    both_present = "EDITED IN PLACE" in text and "— first" in text
    record("LOSS" if not ("EDITED IN PLACE" in text or "— first" in text) else
           ("by design" if both_present else "PASS"),
           "editing a base line in place",
           f"edited kept={'EDITED IN PLACE' in text}, original restored={'— first' in text}")

    print("\n== 7. a server added straight into the rendered servers.json")
    fresh_repo({"model": "base-model"})
    servers = REPO / "shared" / "mcp" / "servers.json"
    data = json.loads(servers.read_text())
    data["servers"]["hand-added"] = {"url": "https://hand.invalid"}
    servers.write_text(json.dumps(data, indent=2) + "\n")
    subprocess.run([sys.executable, str(REPO / "scripts" / "render_settings.py")],
                   cwd=str(REPO), capture_output=True)
    after_servers = json.loads(servers.read_text())["servers"]
    record("by design" if "hand-added" not in after_servers else "PASS",
           "editing the rendered servers.json does not stick",
           "the artifact is regenerated from servers.base.json plus overlays")

    print("\n== 8. an overlay whose file name the base already uses")
    fresh_repo({"model": "base-model"})
    (REPO / "shared" / "memory" / "collision.md").write_text("base version\n")
    make_overlay("clash", 60)
    (ORIGINS / "clash" / "memory" / "collision.md").write_text("overlay version\n")
    git(ORIGINS / "clash", "add", "-A")
    git(ORIGINS / "clash", "commit", "-qm", "clash")
    overlay_cli("add", "clash", str(ORIGINS / "clash"), "--priority", "60")
    result = overlay_cli("install", "clash")
    kept = (REPO / "shared" / "memory" / "collision.md").read_text().strip()
    record("PASS" if result.returncode != 0 and kept == "base version" else "LOSS",
           "an existing base file is never overwritten",
           f"exit={result.returncode}, content={kept!r}")

    print("\n== 9. does the order overlays are applied in change the outcome?")
    for order in (("low", "high"), ("high", "low")):
        fresh_repo({"model": "base-model"})
        make_overlay("low", 10, settings={"shared": "from-low", "onlyLow": 1})
        make_overlay("high", 90, settings={"shared": "from-high", "onlyHigh": 1})
        for alias in order:
            prio = "10" if alias == "low" else "90"
            overlay_cli("add", alias, str(ORIGINS / alias), "--priority", prio)
            overlay_cli("install", alias)
        result = live()
        record(
            "PASS" if result.get("shared") == "from-high" else "LOSS",
            f"settings: install order {order} still lets priority decide",
            f"shared={result.get('shared')}, onlyLow={result.get('onlyLow')}, onlyHigh={result.get('onlyHigh')}",
        )

    fresh_repo({"model": "base-model"})
    make_overlay("tie-a", 50, settings={"shared": "from-a"})
    make_overlay("tie-b", 50, settings={"shared": "from-b"})
    for alias in ("tie-b", "tie-a"):
        overlay_cli("add", alias, str(ORIGINS / alias), "--priority", "50")
    overlay_cli("install")
    record("by design", "equal priority is broken by alias, not by install order",
           f"shared={live().get('shared')} (alphabetically last alias wins)")

    print("\n== 10. two overlays claiming the same file")
    for first, second, label in (("low", "high", "low first, then high"),
                                 ("high", "low", "high first, then low")):
        fresh_repo({"model": "base-model"})
        for alias, prio in (("low", 10), ("high", 90)):
            make_overlay(alias, prio)
            (ORIGINS / alias / "memory" / "contested.md").write_text(
                f"---\nname: contested\n---\n\nfrom {alias}\n"
            )
            git(ORIGINS / alias, "add", "-A")
            git(ORIGINS / alias, "commit", "-qm", "contested")
        for alias in (first, second):
            prio = "10" if alias == "low" else "90"
            overlay_cli("add", alias, str(ORIGINS / alias), "--priority", prio)
        r1 = overlay_cli("install", first)
        r2 = overlay_cli("install", second)
        link = REPO / "shared" / "memory" / "contested.md"
        owner = link.resolve().parent.parent.name if link.is_symlink() else "none"
        record(
            "by design" if r2.returncode != 0 else "PASS",
            f"files: {label}",
            f"second install exit={r2.returncode}, owner={owner}",
        )

    print("\n== 11. appending to a list instead of replacing it")
    fresh_repo({"hooks": {"Stop": [{"id": "base-stop"}]}, "permissions": {"allow": ["base-rule"]}})
    make_overlay("adder", 60, settings={"hooks": {"Stop+": [{"id": "overlay-stop"}]},
                                        "permissions": {"allow+": ["overlay-rule"]}})
    overlay_cli("add", "adder", str(ORIGINS / "adder"), "--priority", "60")
    overlay_cli("install", "adder")
    result = live()
    stop_ids = [h.get("id") for h in result["hooks"]["Stop"]]
    record("PASS" if stop_ids == ["base-stop", "overlay-stop"] else "LOSS",
           "a `key+` fragment appends in source order", f"Stop={stop_ids}")
    record("PASS" if result["permissions"]["allow"] == ["base-rule", "overlay-rule"] else "LOSS",
           "the same works for a nested list", str(result["permissions"]["allow"]))
    record("PASS" if "Stop+" not in result["hooks"] else "LOSS",
           "the `+` key does not survive into the artifact", str(list(result["hooks"])))

    fresh_repo({"model": "base-model"})
    make_overlay("first", 10, settings={"hooks": {"Stop+": [{"id": "from-low"}]}})
    make_overlay("second", 90, settings={"hooks": {"Stop+": [{"id": "from-high"}]}})
    for alias, prio in (("second", "90"), ("first", "10")):
        overlay_cli("add", alias, str(ORIGINS / alias), "--priority", prio)
    overlay_cli("install")
    ids = [h.get("id") for h in live()["hooks"]["Stop"]]
    record("PASS" if ids == ["from-low", "from-high"] else "LOSS",
           "two overlays appending land in priority order, not install order", f"Stop={ids}")

    print(f"\n{sum(1 for v, _, _ in FINDINGS if v == 'PASS')} pass, "
          f"{sum(1 for v, _, _ in FINDINGS if v == 'by design')} by design, "
          f"{sum(1 for v, _, _ in FINDINGS if v == 'LOSS')} loss")
    return 1 if any(v == "LOSS" for v, _, _ in FINDINGS) else 0


if __name__ == "__main__":
    sys.exit(main())
