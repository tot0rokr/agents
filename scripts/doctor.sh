#!/usr/bin/env bash
# Verify the agents repo layout: internal symlinks resolve, JSON/TOML configs
# parse, and (if install.sh has run) the home-dir links point at this repo.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
fail=0

check_link() {
  local path="$1" expected="$2"
  if [[ ! -L "$path" ]]; then
    echo "FAIL  not a symlink: $path"
    fail=1
    return
  fi
  local target
  target="$(readlink "$path")"
  if [[ "$target" != "$expected" ]]; then
    echo "FAIL  $path -> $target (expected $expected)"
    fail=1
    return
  fi
  if [[ ! -e "$path" ]]; then
    echo "FAIL  dangling symlink: $path -> $target"
    fail=1
    return
  fi
  echo "OK    $path -> $target"
}

echo "== internal symlinks =="
check_link "$REPO_ROOT/claude/CLAUDE.md"      "../shared/AGENTS.md"
check_link "$REPO_ROOT/claude/skills"         "../universal/skills"
check_link "$REPO_ROOT/claude/agents"         "../shared/subagents"
check_link "$REPO_ROOT/claude/commands"       "../shared/commands"
check_link "$REPO_ROOT/claude/memory"         "../shared/memory"
check_link "$REPO_ROOT/claude/output-styles"  "../shared/output-styles"
check_link "$REPO_ROOT/codex/AGENTS.md"       "../shared/AGENTS.md"
check_link "$REPO_ROOT/codex/prompts"         "../shared/commands"
check_link "$REPO_ROOT/opencode/AGENTS.md"    "../shared/AGENTS.md"
check_link "$REPO_ROOT/opencode/agents"       "../shared/subagents"
check_link "$REPO_ROOT/opencode/commands"     "../shared/commands"
check_link "$REPO_ROOT/gemini/GEMINI.md"      "../shared/AGENTS.md"

echo
echo "== config files parse =="
parse_json() {
  if python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$1" 2>/dev/null; then
    echo "OK    $1"
  else
    echo "FAIL  $1 (invalid JSON)"
    fail=1
  fi
}
parse_toml() {
  if python3 - "$1" <<'PY' 2>/dev/null; then
import sys
try:
    import tomllib
except ImportError:
    import tomli as tomllib
tomllib.loads(open(sys.argv[1], 'rb').read().decode())
PY
    echo "OK    $1"
  else
    echo "FAIL  $1 (invalid TOML)"
    fail=1
  fi
}

parse_json "$REPO_ROOT/claude/settings.json"
parse_json "$REPO_ROOT/opencode/opencode.json"
parse_json "$REPO_ROOT/gemini/settings.json"
parse_json "$REPO_ROOT/shared/mcp/servers.json"
parse_toml "$REPO_ROOT/codex/config.toml"

echo
echo "== home-dir links (run scripts/install.sh to create) =="
check_home() {
  local target="$1" expected="$2"
  if [[ -L "$target" && "$(readlink "$target")" == "$expected" ]]; then
    echo "OK    $target -> $expected"
  elif [[ -e "$target" ]]; then
    echo "SKIP  $target exists but not linked to $expected"
  else
    echo "SKIP  $target not installed"
  fi
}
check_home "$HOME/.claude"           "$REPO_ROOT/claude"
check_home "$HOME/.codex"            "$REPO_ROOT/codex"
check_home "$HOME/.config/opencode"  "$REPO_ROOT/opencode"
check_home "$HOME/.gemini"           "$REPO_ROOT/gemini"
check_home "$HOME/.agents"           "$REPO_ROOT/universal"

echo
if [[ $fail -eq 0 ]]; then
  echo "doctor: all checks passed"
else
  echo "doctor: $fail failure(s)"
fi
exit $fail
