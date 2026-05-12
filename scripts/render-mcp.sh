#!/usr/bin/env bash
# Render shared/mcp/servers.json into each tool's native MCP config block.
#
# Sources:   shared/mcp/servers.json   (canonical)
# Targets:   claude/settings.json              (.mcpServers)
#            codex/config.toml                 ([mcp_servers.<name>])
#            opencode/opencode.json            (.mcp)
#            gemini/settings.json              (.mcpServers)
#
# Requires:  jq, python3 (for TOML rendering)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$REPO_ROOT/shared/mcp/servers.json"

[[ -f "$SRC" ]] || { echo "missing $SRC" >&2; exit 1; }
command -v jq >/dev/null || { echo "jq is required" >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 1; }

SERVERS="$(jq '.servers // {}' "$SRC")"

# --- Claude: settings.json .mcpServers ---
CLAUDE_FILE="$REPO_ROOT/claude/settings.json"
tmp="$(mktemp)"
jq --argjson s "$SERVERS" '.mcpServers = $s' "$CLAUDE_FILE" > "$tmp" && mv "$tmp" "$CLAUDE_FILE"
echo "wrote $CLAUDE_FILE"

# --- OpenCode: opencode.json .mcp ---
# OpenCode wraps each server with {type: "local", command: [...], enabled: true}.
OPENCODE_FILE="$REPO_ROOT/opencode/opencode.json"
tmp="$(mktemp)"
jq --argjson s "$SERVERS" '
  .mcp = ($s | to_entries | map({
    key: .key,
    value: (
      if (.value.url // .value.httpUrl) then
        {type: "remote", url: (.value.url // .value.httpUrl), enabled: true}
      else
        {type: "local", command: ([.value.command] + (.value.args // [])), enabled: true, environment: (.value.env // {})}
      end
    )
  }) | from_entries)
' "$OPENCODE_FILE" > "$tmp" && mv "$tmp" "$OPENCODE_FILE"
echo "wrote $OPENCODE_FILE"

# --- Gemini: settings.json .mcpServers (same shape as canonical) ---
GEMINI_FILE="$REPO_ROOT/gemini/settings.json"
tmp="$(mktemp)"
jq --argjson s "$SERVERS" '.mcpServers = $s' "$GEMINI_FILE" > "$tmp" && mv "$tmp" "$GEMINI_FILE"
echo "wrote $GEMINI_FILE"

# --- Codex: config.toml [mcp_servers.<name>] ---
# Preserve everything in config.toml above the `[mcp_servers]` marker and
# replace what follows with regenerated TOML.
CODEX_FILE="$REPO_ROOT/codex/config.toml"
python3 - "$SRC" "$CODEX_FILE" <<'PY'
import json, sys, pathlib, re

src, dst = sys.argv[1], sys.argv[2]
servers = json.loads(pathlib.Path(src).read_text()).get("servers", {})
text = pathlib.Path(dst).read_text()
marker = "[mcp_servers]"
head = text.split(marker, 1)[0].rstrip() + "\n\n"

def toml_value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        return "[" + ", ".join(toml_value(x) for x in v) + "]"
    if isinstance(v, dict):
        # inline table
        return "{ " + ", ".join(f"{k} = {toml_value(val)}" for k, val in v.items()) + " }"
    return json.dumps(str(v))

out = [head, "[mcp_servers]\n"]
for name, cfg in servers.items():
    out.append(f"\n[mcp_servers.{name}]\n")
    for key, val in cfg.items():
        out.append(f"{key} = {toml_value(val)}\n")

pathlib.Path(dst).write_text("".join(out))
print(f"wrote {dst}")
PY
