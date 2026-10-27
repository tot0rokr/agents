#!/usr/bin/env bash
# Regenerate codex/config.toml (and codex/AGENTS.override.md).
#
# Both are render artifacts of scripts/render_settings.py, which renders every
# artifact in one pass; this name is kept for whoever still calls it.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec python3 "$REPO_ROOT/scripts/render_settings.py" "$@"
