#!/usr/bin/env bash
# Regenerate codex/config.toml from canonical sources.
#
# Currently this only re-renders the [mcp_servers] block. Hooks and agents
# are written by hand below the `[mcp_servers]` section because Codex's
# TOML schema for those features doesn't map cleanly from JSON.
#
# This script is a thin wrapper that re-uses render-mcp.sh's logic.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec "$REPO_ROOT/scripts/render-mcp.sh"
