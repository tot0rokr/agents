#!/usr/bin/env bash
# Render shared/mcp/servers.json into each tool's native MCP config block.
#
# Canonical schema (shared/mcp/servers.json):
#   {
#     "servers": {
#       "<name>": {
#         "description": "optional human note (not propagated to every tool)",
#         "url": "https://...",          # remote: HTTP or SSE endpoint
#         "transport": "http" | "sse",   # default "http" when url is set
#         "headers": { ... },            # remote: optional HTTP headers
#         "command": "npx",              # stdio: executable
#         "args": ["-y", "..."],         # stdio: argv tail
#         "env":  { "FOO": "bar" },      # stdio: environment vars
#         "enabled": true                # default true
#       }
#     }
#   }
#
# Targets (all overwritten in place):
#   ~/.claude.json                 .mcpServers   (NOT claude/settings.json —
#                                                  Claude Code reads MCP from
#                                                  the home-level file, not
#                                                  the settings.json inside
#                                                  ~/.claude/. This script
#                                                  patches the user's
#                                                  ~/.claude.json in place
#                                                  and preserves all other
#                                                  keys.)
#   opencode/opencode.json         .mcp
#   gemini/settings.json           .mcpServers
#
# Codex is not here: codex/config.toml is a render artifact, and
# scripts/render_settings.py writes its [mcp_servers] along with the rest.
#
# Requires:  jq

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Two sources, because the outputs have two audiences. servers.json is the
# rendered, overlay-merged set: it may name an employer's internal servers and
# carry their credentials, and it is the right thing for this machine's own
# ~/.claude.json. The per-tool configs under gemini/ and opencode/ are tracked
# in a public repo, so they are rendered from the base alone.
SRC="$REPO_ROOT/shared/mcp/servers.json"
PUBLIC_SRC="$REPO_ROOT/shared/mcp/servers.base.json"
[[ -f "$PUBLIC_SRC" ]] || PUBLIC_SRC="$SRC"   # a repo from before the split

[[ -f "$SRC" ]] || { echo "missing $SRC" >&2; exit 1; }
command -v jq >/dev/null || { echo "jq is required" >&2; exit 1; }

# Shared jq helper functions: classify a server, then map it per tool.
JQ_LIB='
def is_remote: (.url // null) != null;
def is_stdio:  (.command // null) != null;
def transport: (.transport // "http");

def to_claude:
  if is_remote then
    { type: transport, url: .url }
    + (if .headers then { headers: .headers } else {} end)
  else
    { command: .command, args: (.args // []) }
    + (if .env then { env: .env } else {} end)
  end;

def to_gemini:
  if is_remote then
    (if transport == "sse" then { url: .url } else { httpUrl: .url } end)
    + (if .headers then { headers: .headers } else {} end)
  else
    { command: .command, args: (.args // []) }
    + (if .env then { env: .env } else {} end)
  end;

def to_opencode:
  if is_remote then
    { type: "remote", url: .url, enabled: (.enabled // true) }
    + (if .headers then { headers: .headers } else {} end)
  else
    { type: "local",
      command: ([.command] + (.args // [])),
      enabled: (.enabled // true),
      environment: (.env // {}) }
  end;

def map_servers(f):
  to_entries | map({ key: .key, value: (.value | f) }) | from_entries;
'

SERVERS_RAW="$(jq '.servers // {}' "$SRC")"
PUBLIC_SERVERS_RAW="$(jq '.servers // {}' "$PUBLIC_SRC")"

# --- Claude: $HOME/.claude.json .mcpServers ---
# Claude Code's MCP servers live at the home-level `~/.claude.json`, not
# inside `~/.claude/settings.json`. settings.json carries hooks,
# permissions, and theme; mcpServers there is silently ignored. Patch the
# real file in place, preserving every other key (Claude Code stores 28+ KB
# of runtime state there — onboarding flags, project history, caches).
CLAUDE_HOME_FILE="${HOME}/.claude.json"
if [[ -f "$CLAUDE_HOME_FILE" ]]; then
  # Merge rather than replace. A value that exists only on this machine — a
  # password deliberately kept out of every repo — has to survive the render,
  # and a server registered here by hand must not be dropped.
  tmp="$(mktemp)"
  jq --argjson s "$SERVERS_RAW" "$JQ_LIB"'
    .mcpServers = ((.mcpServers // {}) as $cur
      | $cur + (($s | map_servers(to_claude))
                | with_entries(.value = (($cur[.key] // {}) * .value))))
  ' "$CLAUDE_HOME_FILE" > "$tmp" && mv "$tmp" "$CLAUDE_HOME_FILE"
  chmod 600 "$CLAUDE_HOME_FILE"
  echo "patched $CLAUDE_HOME_FILE (.mcpServers updated; other keys preserved)"
else
  jq -n --argjson s "$SERVERS_RAW" "$JQ_LIB"'
    { mcpServers: ($s | map_servers(to_claude)) }
  ' > "$CLAUDE_HOME_FILE"
  chmod 600 "$CLAUDE_HOME_FILE"
  echo "created $CLAUDE_HOME_FILE"
fi

# Cleanup: drop any stale `.mcpServers` key inside claude/settings.json so
# the version-controlled file doesn't pretend to define MCP servers.
CLAUDE_FILE="$REPO_ROOT/claude/settings.json"
if [[ -f "$CLAUDE_FILE" ]] && jq -e '.mcpServers' "$CLAUDE_FILE" >/dev/null 2>&1; then
  tmp="$(mktemp)"
  jq 'del(.mcpServers)' "$CLAUDE_FILE" > "$tmp" && mv "$tmp" "$CLAUDE_FILE"
  echo "scrubbed stale .mcpServers from $CLAUDE_FILE"
fi

# --- Gemini: settings.json .mcpServers ---
GEMINI_FILE="$REPO_ROOT/gemini/settings.json"
tmp="$(mktemp)"
jq --argjson s "$PUBLIC_SERVERS_RAW" "$JQ_LIB"'
  .mcpServers = ($s | map_servers(to_gemini))
' "$GEMINI_FILE" > "$tmp" && mv "$tmp" "$GEMINI_FILE"
echo "wrote $GEMINI_FILE"

# --- OpenCode: opencode.json .mcp ---
OPENCODE_FILE="$REPO_ROOT/opencode/opencode.json"
tmp="$(mktemp)"
jq --argjson s "$PUBLIC_SERVERS_RAW" "$JQ_LIB"'
  .mcp = ($s | map_servers(to_opencode))
' "$OPENCODE_FILE" > "$tmp" && mv "$tmp" "$OPENCODE_FILE"
echo "wrote $OPENCODE_FILE"
