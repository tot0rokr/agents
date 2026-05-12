#!/usr/bin/env bash
# Regenerate gemini/settings.json's MCP block from canonical sources.
#
# Hooks and agents in settings.json are hand-edited (their schemas don't have
# a clean canonical source). MCP is the only generated section right now.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec "$REPO_ROOT/scripts/render-mcp.sh"
