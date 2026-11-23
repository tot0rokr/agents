"""The layers the harness is assembled from: the base (this repo) and the overlays.

The base is layer 0, shaped like an overlay. Its own files (manifest, setup
steps, settings and MCP fragments, memory index) live under base/ with the
names an overlay uses under overlays/<alias>/. Its memory, instructions,
commands, subagents and skills are the view directories themselves, so
applying it links nothing. Overlays (overlay.Overlay) bring theirs in, in
priority order, on top of the base.

This module imports nothing from overlay or render_settings at load time;
both import it.
"""

from __future__ import annotations

import json
import os
import re
import socket
from pathlib import Path

BASE_ALIAS = "base"
BASE_PRIORITY = 0
BASE_DIR_REL = "base"
BASE_MANIFEST_REL = "base/overlay.json"

# How a layer's files reach the view directories the tools read.
#   inplace:  they are already there (the base)
#   symlink:  each file, or each skill directory, is symlinked in from the
#             overlay clone (overlays/<alias>/memory/x.md and so on)
#   checkout: the overlay clone's worktree is the harness root, so its view
#             files are real files in the view directories, tracked in place
#             by the overlay's own git (docs/overlay.md)
APPLY_INPLACE = "inplace"
APPLY_SYMLINK = "symlink"
APPLY_CHECKOUT = "checkout"
# What an overlay may use. Without an "apply" key in its manifest, the clone's
# layout decides (overlay.Overlay.apply_mode).
OVERLAY_APPLY_MODES = (APPLY_SYMLINK, APPLY_CHECKOUT)

# Overlay-relative directory -> the view directory the base and the overlays fill.
VIEW_DIRS = {
    "memory": "shared/memory",
    "instructions": "shared/instructions",
    "commands": "shared/commands",
    "subagents": "shared/subagents",
    "skills": "universal/skills",
}

# Overlay-relative file -> where the base keeps the same part: the same name
# under base/ as under overlays/<alias>/.
BASE_PATHS = {
    rel: f"{BASE_DIR_REL}/{rel}"
    for rel in ("settings/claude.json", "settings/codex.toml", "mcp/servers.json", "memory/MEMORY.md")
}


# An overlay's memory index lines for one machine only:
# overlays/<alias>/memory/hosts/<host>.md joins the index on that host alone.
MEMORY_HOSTS_REL = "memory/hosts"
HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def current_host() -> str:
    """This machine's short host name. AGENTS_HOST overrides it (tests, a renamed machine)."""
    return os.environ.get("AGENTS_HOST") or socket.gethostname().split(".")[0]


class BaseLayer:
    """The harness repo itself, seen through the interface overlays have."""

    alias = BASE_ALIAS
    priority = BASE_PRIORITY
    enabled = True
    cloned = True
    is_base = True
    apply_mode = APPLY_INPLACE

    def __init__(self, repo_root: Path):
        self.repo_root = repo_root

    def manifest(self) -> dict:
        target = self.repo_root / BASE_MANIFEST_REL
        return json.loads(target.read_text()) if target.is_file() else {}

    def variables(self) -> dict:
        return {"CLAUDE_HOME": str(Path.home())}

    def real_path(self, rel: str) -> Path:
        """Where the base keeps the part an overlay keeps at `rel`."""
        if rel in BASE_PATHS:
            return self.repo_root / BASE_PATHS[rel]
        head, _, tail = rel.partition("/")
        if head in VIEW_DIRS:
            view = self.repo_root / VIEW_DIRS[head]
            return view / tail if tail else view
        return self.repo_root / BASE_DIR_REL / rel


def layers(repo_root: Path) -> list:
    """The base, then the enabled overlays in merge order (priority, then alias)."""
    from overlay import enabled_overlays  # local import: overlay imports this module

    return [BaseLayer(repo_root), *enabled_overlays(repo_root)]
