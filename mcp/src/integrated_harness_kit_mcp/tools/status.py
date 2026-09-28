"""status / capabilities — one place to ask "is this harness healthy?"."""

from __future__ import annotations

import os
from pathlib import Path

from .. import layout, repo as repo_lib, repo_scripts
from ._common import need_repo, run

# home path -> repo directory it should point at
LINKS: tuple[tuple[str, str], ...] = (
    (".claude", "claude"),
    (".codex", "codex"),
    (".config/opencode", "opencode"),
    (".gemini", "gemini"),
    (".agents", "universal"),
)


def capabilities(repo_path: str | None = None) -> dict:
    """What the repo on this machine supports — overlays, renderers, scripts."""
    repo_root = repo_lib.find_repo(Path(repo_path) if repo_path else None)
    caps = repo_scripts.capabilities(repo_root)
    caps["package_version"] = _version()
    return caps


def status(level: str = "quick", repo_path: str | None = None, home: str | None = None) -> dict:
    """Repo presence, home symlinks, overlays — and with level="full", doctor.

    Args:
        level: "quick" (no subprocess) or "full" (also runs scripts/doctor.sh).
        home: override `$HOME` when checking the symlinks. For tests.
    """
    if level not in ("quick", "full"):
        return {"ok": False, "error": f"unknown level {level!r}; expected quick or full"}

    repo_root, fail = need_repo(repo_path)
    if fail:
        return fail

    home_root = Path(home).expanduser() if home else Path(os.path.expanduser("~"))
    links = []
    for home_rel, repo_rel in LINKS:
        target = home_root / home_rel
        expected = repo_root / repo_rel
        if target.is_symlink():
            actual = Path(os.readlink(target))
            state = "linked" if actual == expected else "linked-elsewhere"
        elif target.exists():
            state = "real-directory"
        else:
            state = "missing"
        links.append(
            {
                "path": str(target),
                "expected": str(expected),
                "state": state,
                "ok": state == "linked",
            }
        )

    result = {
        "ok": all(entry["ok"] for entry in links),
        "repo": str(repo_root),
        "links": links,
        "artifacts": _artifacts(repo_root),
        "overlays": _overlays(repo_root),
    }

    if level == "full":
        doctor = repo_root / "scripts" / "doctor.sh"
        if doctor.is_file():
            result["doctor"] = run(["bash", str(doctor)], cwd=repo_root, timeout=120.0)
            result["ok"] = result["ok"] and result["doctor"]["ok"]
        else:
            result["doctor"] = {"ok": False, "stderr": f"missing script: {doctor}"}
            result["ok"] = False

    return result


def _artifacts(repo_root: Path) -> list[dict]:
    out = []
    for artifact, source in layout.ARTIFACTS.items():
        out.append(
            {
                "path": artifact,
                "source": source,
                "rendered": (repo_root / artifact).is_file(),
                "source_present": (repo_root / source).is_file(),
            }
        )
    return out


def _overlays(repo_root: Path) -> dict:
    if not layout.supports_overlays(repo_root):
        return {"supported": False, "installed": []}

    applied = layout.applied_links(repo_root)
    counts: dict[str, int] = {}
    for alias in applied.values():
        counts[alias] = counts.get(alias, 0) + 1

    installed = []
    for entry in layout.registered_overlays(repo_root):
        alias = entry.get("alias", "")
        root = layout.overlay_root(repo_root, alias)
        installed.append(
            {
                "alias": alias,
                "priority": entry.get("priority", 50),
                "enabled": entry.get("enabled", True),
                "url": entry.get("url", ""),
                "ref": entry.get("ref", ""),
                "cloned": (root / "overlay.json").is_file(),
                "links": counts.get(alias, 0),
            }
        )
    return {"supported": True, "installed": installed}


def _version() -> str:
    try:
        from .. import __version__  # noqa: PLC0415

        return __version__
    except Exception:  # noqa: BLE001
        return "unknown"
