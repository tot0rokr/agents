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
# Exit 2 means no TOML reader (Python < 3.11 without tomli), which says nothing
# about the file, so it is no "invalid TOML". It does mean the renderer skips
# codex/config.toml, which is worth a WARN.
parse_toml() {
  python3 - "$1" <<'PY' 2>/dev/null
import sys
try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        sys.exit(2)
tomllib.loads(open(sys.argv[1], 'rb').read().decode())
PY
  case $? in
    0) echo "OK    $1" ;;
    2) echo "WARN  $1 not checked, and codex/config.toml not rendered: no TOML reader (needs Python 3.11+ or the tomli package)" ;;
    *) echo "FAIL  $1 (invalid TOML)"; fail=1 ;;
  esac
}

# Both carry the overlay-merged MCP servers, credentials included, so the
# renderer writes them 600; either one left readable exposes them.
warn_unless_private() {
  local mode
  [[ -f "$REPO_ROOT/$1" ]] || return 0
  mode="$(stat -c %a "$REPO_ROOT/$1" 2>/dev/null || stat -f %Lp "$REPO_ROOT/$1")"
  if [[ "$mode" != "600" ]]; then
    echo "WARN  $1 is mode $mode, not 600 — it can hold MCP credentials; re-run scripts/render_settings.py"
  fi
}

if [[ -f "$REPO_ROOT/claude/settings.json" ]]; then
  parse_json "$REPO_ROOT/claude/settings.json"
else
  echo "SKIP  $REPO_ROOT/claude/settings.json not rendered yet (scripts/render_settings.py)"
fi
parse_json "$REPO_ROOT/claude/settings.base.json"
parse_json "$REPO_ROOT/opencode/opencode.json"
parse_json "$REPO_ROOT/gemini/settings.json"
parse_json "$REPO_ROOT/shared/mcp/servers.json"
warn_unless_private shared/mcp/servers.json
parse_toml "$REPO_ROOT/codex/config.base.toml"
if [[ -f "$REPO_ROOT/codex/config.toml" ]]; then
  parse_toml "$REPO_ROOT/codex/config.toml"
  warn_unless_private codex/config.toml
else
  echo "SKIP  codex/config.toml not rendered yet (scripts/render_settings.py)"
  # Until 2026-10 the file was tracked, so the pull that untracked it deleted it
  # where Codex had not modified it. Ask the renderer which copy it would read
  # back: a clone made after that commit never had one, and must not be handed
  # somebody else's old config.
  restore_from="$(python3 - "$REPO_ROOT" <<'PY' 2>/dev/null
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1] + "/scripts")
import render_settings
copy = render_settings.last_checked_out_copy(Path(sys.argv[1]), "codex/config.toml")
print(copy[0][:12] if copy else "")
PY
)"
  if [[ -n "$restore_from" ]]; then
    echo "      A pull deleted the copy this checkout had; the first render restores it. By hand:"
    printf '      git -C "%s" show %s:codex/config.toml > "%s/codex/config.toml"\n' "$REPO_ROOT" "$restore_from" "$REPO_ROOT"
  fi
fi
if [[ -f "$REPO_ROOT/codex/AGENTS.override.md" ]]; then
  # No limit to check: Codex reads this global file whole. Its 32 KiB
  # project_doc_max_bytes caps only the AGENTS.md (and AGENTS.override.md)
  # files it finds in a project.
  agents_size="$(wc -c < "$REPO_ROOT/codex/AGENTS.override.md")"
  echo "OK    codex/AGENTS.override.md ($((agents_size)) bytes)"
fi

echo
echo "== overlays (see docs/overlay.md) =="
# --check prints one line per base: OK, FAIL (a local-only key, or a file
# that does not parse) or SKIP (no TOML reader).
check_out="$(python3 "$REPO_ROOT/scripts/render_settings.py" --check 2>&1)"
check_rc=$?
grep -E '^(OK|FAIL|SKIP) ' <<<"$check_out"
if (( check_rc != 0 )); then
  grep -q '^FAIL' <<<"$check_out" || echo "FAIL  scripts/render_settings.py --check failed"
  fail=1
fi
if [[ -d "$REPO_ROOT/overlays" ]]; then
  overlays_mode="$(stat -c %a "$REPO_ROOT/overlays" 2>/dev/null || stat -f %Lp "$REPO_ROOT/overlays")"
  if [[ "$overlays_mode" != "700" ]]; then
    # The clones hold credentials (servers.local.json, vars.local.json) at the umask's mode.
    echo "WARN  overlays/ is mode $overlays_mode, not 700 — other users can read the overlays' credentials; scripts/overlay.py install closes it"
  fi
fi
tracked_artifacts="$(git -C "$REPO_ROOT" ls-files -- claude/settings.json shared/mcp/servers.json shared/memory/MEMORY.md codex/config.toml codex/AGENTS.override.md)"
if [[ -n "$tracked_artifacts" ]]; then
  echo "FAIL  render artifacts are tracked by git: $(echo $tracked_artifacts) — git rm --cached them"
  fail=1
else
  echo "OK    render artifacts are untracked"
fi
if python3 "$REPO_ROOT/scripts/overlay.py" status >/dev/null 2>&1; then
  echo "OK    overlay links and settings render are in sync"
else
  echo "WARN  overlay drift — run scripts/overlay.py status"
fi

echo
echo "== rendered configs carry no overlay content =="
leak_report="$(python3 - "$REPO_ROOT" <<'PY'
import json, sys
from pathlib import Path

repo = Path(sys.argv[1])
TRACKED = ("opencode/opencode.json", "gemini/settings.json")


def servers(rel):
    path = repo / rel
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text()).get("servers") or {}
    except (OSError, json.JSONDecodeError):
        return {}


overlay_only = sorted(set(servers("shared/mcp/servers.json")) - set(servers("shared/mcp/servers.base.json")))
if not overlay_only:
    print("OK    no overlay-only MCP servers to leak")
    raise SystemExit(0)

hits = []
for rel in TRACKED:
    path = repo / rel
    if not path.is_file():
        continue
    text = path.read_text()
    found = [name for name in overlay_only if name in text]
    if found:
        hits.append(f"{rel}: {', '.join(found)}")

if hits:
    for hit in hits:
        print(f"FAIL  overlay server in a tracked config — {hit}")
    raise SystemExit(1)
print(f"OK    {len(overlay_only)} overlay-only server(s) stayed out of the tracked configs")
PY
)" || fail=1
echo "$leak_report"

echo
echo "== registered harness MCP entry =="
claude_json="$HOME/.claude.json"
if [[ -f "$claude_json" ]]; then
  entry_cmd="$(python3 - "$claude_json" <<'PY'
import json, sys
try:
    servers = json.load(open(sys.argv[1])).get("mcpServers") or {}
except Exception:
    raise SystemExit(0)
for name, cfg in servers.items():
    if "harness" in name:
        print(" ".join([cfg.get("command", "")] + list(cfg.get("args") or [])))
        break
PY
)"
  if [[ -z "$entry_cmd" ]]; then
    echo "SKIP  no harness MCP server registered in ~/.claude.json"
  else
    read -r -a entry_parts <<< "$entry_cmd"
    if command -v "${entry_parts[0]}" >/dev/null 2>&1; then
      echo "OK    registered as: $entry_cmd"
    else
      echo "FAIL  registered command not on PATH: ${entry_parts[0]}"
      fail=1
    fi
    for part in "${entry_parts[@]}"; do
      if [[ "$part" == /* && ! -e "$part" ]]; then
        echo "FAIL  registered path does not exist: $part"
        fail=1
      fi
    done
  fi
else
  echo "SKIP  ~/.claude.json not present"
fi

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
