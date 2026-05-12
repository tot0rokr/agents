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
#   claude/settings.json           .mcpServers
#   codex/config.toml              [mcp_servers.<name>]
#   opencode/opencode.json         .mcp
#   gemini/settings.json           .mcpServers
#
# Requires:  jq, python3 (for TOML rendering)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$REPO_ROOT/shared/mcp/servers.json"

[[ -f "$SRC" ]] || { echo "missing $SRC" >&2; exit 1; }
command -v jq >/dev/null || { echo "jq is required" >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 1; }

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

# --- Claude: settings.json .mcpServers ---
CLAUDE_FILE="$REPO_ROOT/claude/settings.json"
tmp="$(mktemp)"
jq --argjson s "$SERVERS_RAW" "$JQ_LIB"'
  .mcpServers = ($s | map_servers(to_claude))
' "$CLAUDE_FILE" > "$tmp" && mv "$tmp" "$CLAUDE_FILE"
echo "wrote $CLAUDE_FILE"

# --- Gemini: settings.json .mcpServers ---
GEMINI_FILE="$REPO_ROOT/gemini/settings.json"
tmp="$(mktemp)"
jq --argjson s "$SERVERS_RAW" "$JQ_LIB"'
  .mcpServers = ($s | map_servers(to_gemini))
' "$GEMINI_FILE" > "$tmp" && mv "$tmp" "$GEMINI_FILE"
echo "wrote $GEMINI_FILE"

# --- OpenCode: opencode.json .mcp ---
OPENCODE_FILE="$REPO_ROOT/opencode/opencode.json"
tmp="$(mktemp)"
jq --argjson s "$SERVERS_RAW" "$JQ_LIB"'
  .mcp = ($s | map_servers(to_opencode))
' "$OPENCODE_FILE" > "$tmp" && mv "$tmp" "$OPENCODE_FILE"
echo "wrote $OPENCODE_FILE"

# --- Codex: config.toml [mcp_servers.<name>] ---
# Codex supports both stdio and HTTP natively. We strip all existing
# `[mcp_servers]` and `[mcp_servers.*]` sections, preserve every other
# section in its original order, and append the regenerated MCP block at
# the end. This survives Codex CLI writing its own sections anywhere in
# the file (e.g. [projects."<path>"] for trust settings).
CODEX_FILE="$REPO_ROOT/codex/config.toml"
python3 - "$SRC" "$CODEX_FILE" <<'PY'
import json, re, sys, pathlib

src, dst = sys.argv[1], sys.argv[2]
servers = json.loads(pathlib.Path(src).read_text()).get("servers", {})
text = pathlib.Path(dst).read_text()

header_re = re.compile(r'^\s*\[([^\]]+)\]\s*$')

def is_mcp(section: str) -> bool:
    return section == "mcp_servers" or section.startswith("mcp_servers.")

preserved = []
skipping = False
for line in text.splitlines():
    m = header_re.match(line)
    if m:
        skipping = is_mcp(m.group(1))
    if not skipping:
        preserved.append(line)

while preserved and not preserved[-1].strip():
    preserved.pop()

def toml_value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        return "[" + ", ".join(toml_value(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{ " + ", ".join(f"{k} = {toml_value(val)}" for k, val in v.items()) + " }"
    return json.dumps(str(v))

def to_codex(name, cfg):
    out = []
    if cfg.get("url"):
        out.append(("url", cfg["url"]))
        if cfg.get("headers"):
            out.append(("http_headers", cfg["headers"]))
    else:
        if cfg.get("command"):
            out.append(("command", cfg["command"]))
        if cfg.get("args"):
            out.append(("args", cfg["args"]))
        if cfg.get("env"):
            out.append(("env", cfg["env"]))
    if cfg.get("enabled") is False:
        out.append(("enabled", False))
    return out

parts = ["\n".join(preserved), "\n\n", "[mcp_servers]\n"]
for name, cfg in servers.items():
    parts.append(f"\n[mcp_servers.{name}]\n")
    for key, val in to_codex(name, cfg):
        parts.append(f"{key} = {toml_value(val)}\n")

pathlib.Path(dst).write_text("".join(parts))
print(f"wrote {dst}")
PY
