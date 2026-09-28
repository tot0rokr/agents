"""Load the target repo's own scripts instead of reimplementing them.

This package ships independently of the harness it manages (`uvx
integrated-harness-kit-mcp` against whatever repo is found at call time), so a
copy of the overlay or render logic here would drift from the repo's within a
release or two. Instead the repo's `scripts/` modules are imported directly,
and `capabilities()` reports what the repo on this machine actually supports.
"""

from __future__ import annotations

import importlib.util
import sys
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType

_CACHE: dict[tuple[str, str], ModuleType | None] = {}


@contextmanager
def scripts_on_path(repo_root: Path):
    """Put `<repo>/scripts` on sys.path for the duration of a call.

    The repo's modules import each other by bare name (`render_settings` does
    `from overlay import enabled_overlays` lazily, inside a function), so the
    path has to be there when the function runs, not only when it is imported.
    """
    scripts_dir = str(repo_root / "scripts")
    added = scripts_dir not in sys.path
    if added:
        sys.path.insert(0, scripts_dir)
    try:
        yield
    finally:
        if added and scripts_dir in sys.path:
            sys.path.remove(scripts_dir)


def load(repo_root: Path, module_name: str) -> ModuleType | None:
    """Import `<repo>/scripts/<module_name>.py`, or None if unavailable."""
    key = (str(repo_root), module_name)
    if key in _CACHE:
        return _CACHE[key]

    script = repo_root / "scripts" / f"{module_name}.py"
    if not script.is_file():
        _CACHE[key] = None
        return None

    scripts_dir = str(repo_root / "scripts")
    added = scripts_dir not in sys.path
    if added:
        # overlay.py imports install/render_settings as top-level modules.
        sys.path.insert(0, scripts_dir)
    try:
        unique = f"_harness_{module_name}_{abs(hash(str(repo_root)))}"
        spec = importlib.util.spec_from_file_location(unique, script)
        if spec is None or spec.loader is None:
            _CACHE[key] = None
            return None
        module = importlib.util.module_from_spec(spec)
        # Register before executing: @dataclass resolves field types through
        # sys.modules[cls.__module__], and install.py is full of dataclasses.
        sys.modules[unique] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(unique, None)
            raise
    except Exception:  # noqa: BLE001 — a repo too old or too new must not crash the server
        module = None
    finally:
        if added and scripts_dir in sys.path:
            sys.path.remove(scripts_dir)

    _CACHE[key] = module
    return module


def clear_cache() -> None:
    _CACHE.clear()


def capabilities(repo_root: Path | None) -> dict:
    """What this repo supports, so a caller can degrade instead of failing."""
    if repo_root is None:
        return {"repo": None, "overlays": False, "render_settings": False}

    overlay = load(repo_root, "overlay")
    render = load(repo_root, "render_settings")
    scripts = repo_root / "scripts"

    return {
        "repo": str(repo_root),
        "overlays": overlay is not None and hasattr(overlay, "load_registry"),
        "overlay_route": overlay is not None and hasattr(overlay, "cmd_route"),
        "overlay_setup": overlay is not None and hasattr(overlay, "cmd_setup"),
        "render_settings": render is not None and hasattr(render, "render_all"),
        "render_memory": render is not None and hasattr(render, "render_memory"),
        "shell_renders": sorted(
            p.name for p in scripts.glob("render-*.sh") if p.is_file()
        ),
    }
