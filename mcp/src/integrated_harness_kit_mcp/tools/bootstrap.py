"""bootstrap — take a machine from nothing to a working harness.

`clone` and `install` on their own leave a half-built machine: the base repo is
linked, but the overlays that carry this environment's memories, instructions
and credentials are not, and nothing has been rendered. This runs the whole
sequence and reports each step.
"""

from __future__ import annotations

from pathlib import Path

from .. import layout
from .clone import DEFAULT_DEST, DEFAULT_REPO_URL, clone as _clone
from .install_tool import install as _install
from .overlay import overlay_install
from .render import render as _render
from .status import status as _status


def bootstrap(
    dest: str = DEFAULT_DEST,
    repo_url: str = DEFAULT_REPO_URL,
    with_overlays: bool = True,
    dry_run: bool = False,
    home: str | None = None,
    timeout: float = 300.0,
) -> dict:
    """Clone (if needed), install, render, apply overlays, verify.

    Args:
        with_overlays: apply every registered overlay after installing. A
                       machine without them has no personal or work context.
        dry_run: pass through to the installer and skip the mutating steps.
    """
    steps: list[dict] = []
    dest_path = Path(dest).expanduser()

    if (dest_path / "scripts" / "install.py").is_file():
        steps.append({"step": "clone", "ok": True, "skipped": "repo already present"})
    else:
        result = _clone(dest=str(dest_path), repo_url=repo_url, timeout=timeout)
        steps.append({"step": "clone", **result})
        if not result.get("ok"):
            return _done(steps, dest_path)

    result = _install(repo_path=str(dest_path), home=home, dry_run=dry_run, timeout=timeout)
    steps.append({"step": "install", **result})
    if not result.get("ok") or dry_run:
        return _done(steps, dest_path)

    result = _render(scope="artifacts", repo_path=str(dest_path))
    steps.append({"step": "render", **result})

    if with_overlays and layout.supports_overlays(dest_path):
        registered = layout.registered_overlays(dest_path)
        if registered:
            result = overlay_install(repo_path=str(dest_path))
            steps.append({"step": "overlays", **result})
        else:
            steps.append(
                {
                    "step": "overlays",
                    "ok": True,
                    "skipped": "none registered",
                    "hint": "overlay_add(alias, url) then overlay_install(alias)",
                }
            )

    steps.append(
        {"step": "verify", **_status(level="full", repo_path=str(dest_path), home=home)}
    )
    return _done(steps, dest_path)


def _done(steps: list[dict], dest: Path) -> dict:
    return {
        "ok": all(step.get("ok", False) for step in steps),
        "repo": str(dest),
        "steps": steps,
    }
