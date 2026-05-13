#!/usr/bin/env bash
# Thin shell wrapper around scripts/install.py. The Python implementation
# is the source of truth — it tracks each mutation and auto-rolls back on
# error. Keeping the shell entry point so existing muscle memory works.

set -euo pipefail
exec python3 "$(dirname "$0")/install.py" "$@"
