#!/usr/bin/env bash
# Replay INSTALLATION.md literally, in a container, and check each step.
#
# Every command here is one the document tells the agent to run — if the doc
# drifts from what works, this fails. Assumes /home/agent/source is a git repo
# holding the harness (the container test prepares that).
set -uo pipefail

SOURCE="${1:-/home/agent/source}"
PASS=0
FAIL=0

check() {
    local name="$1" condition="$2" detail="${3:-}"
    if [ "$condition" = "0" ]; then
        echo "  [PASS] $name"
        PASS=$((PASS + 1))
    else
        echo "  [FAIL] $name ${detail:+— $detail}"
        FAIL=$((FAIL + 1))
    fi
}

echo "== Step 1 — current state"
test -d ~/agents && echo "REPO_EXISTS" || echo "REPO_MISSING"

echo "== Step 2 — clone"
git clone -q "$SOURCE" ~/agents
check "repo cloned" $?

echo "== Step 3 — install"
python3 ~/agents/scripts/install.py >/tmp/install.log 2>&1
check "installer exited 0" $? "$(tail -3 /tmp/install.log)"
for p in .claude .codex .config/opencode .gemini .agents; do
    [ -L "$HOME/$p" ]
    check "$p is a symlink" $?
done

echo "== Step 4 — doctor"
bash ~/agents/scripts/doctor.sh >/tmp/doctor.log 2>&1
check "doctor exited 0" $? "$(tail -3 /tmp/doctor.log)"
tail -1 /tmp/doctor.log | grep -q "all checks passed"
check "doctor's last line is the expected one" $? "$(tail -1 /tmp/doctor.log)"

echo "== Step 5 — register the MCP server, exactly as documented"
jq --arg repo "$HOME/agents/mcp" \
   '.mcpServers += {"integrated-harness-kit":{"command":"uvx","args":["--from",$repo,"integrated-harness-kit-mcp"]}}' \
   ~/.claude.json > /tmp/.claude.json.new 2>/dev/null \
   || echo '{"mcpServers":{}}' | jq --arg repo "$HOME/agents/mcp" \
        '.mcpServers += {"integrated-harness-kit":{"command":"uvx","args":["--from",$repo,"integrated-harness-kit-mcp"]}}' \
        > /tmp/.claude.json.new
mv /tmp/.claude.json.new ~/.claude.json && chmod 600 ~/.claude.json
jq -e '.mcpServers["integrated-harness-kit"]' ~/.claude.json >/dev/null
check "entry present in ~/.claude.json" $?

echo '' | timeout 180 uvx --from ~/agents/mcp integrated-harness-kit-mcp >/tmp/server.log 2>&1
check "documented verification command exits quietly" $? "$(tail -3 /tmp/server.log)"
grep -qi "traceback\|ModuleNotFoundError" /tmp/server.log
check "no traceback from the server" $([ $? -eq 0 ] && echo 1 || echo 0) "$(tail -3 /tmp/server.log)"

echo "== Step 6 — overlays"
ORIGIN=~/walkthrough-overlay
mkdir -p "$ORIGIN/memory"
cat > "$ORIGIN/overlay.json" <<'JSON'
{
  "name": "personal",
  "priority": 50,
  "setup": [
    {"id": "needs-a-human", "description": "a credential only the user has",
     "check": "test -f $HOME/.walkthrough-secret",
     "manual": "Ask the user for the token and write it to $HOME/.walkthrough-secret"}
  ]
}
JSON
cat > "$ORIGIN/memory/machine_note.md" <<'MD'
---
name: machine_note
description: a fact about this machine
---

Only this machine knows it.
MD
git -C "$ORIGIN" init -q -b main
git -C "$ORIGIN" -c user.name=w -c user.email=w@e add -A
git -C "$ORIGIN" -c user.name=w -c user.email=w@e commit -qm overlay

python3 ~/agents/scripts/overlay.py add personal "$ORIGIN" --priority 50 >/tmp/ov.log 2>&1
check "overlay registered" $? "$(tail -2 /tmp/ov.log)"
python3 ~/agents/scripts/overlay.py install personal >>/tmp/ov.log 2>&1
check "overlay installed" $? "$(tail -2 /tmp/ov.log)"
[ -L ~/agents/shared/memory/machine_note.md ]
check "overlay memory linked into the base tree" $?
[ -L ~/.claude/memory/machine_note.md ]
check "reachable through ~/.claude too" $?

python3 ~/agents/scripts/overlay.py setup personal --dry-run >/tmp/setup.log 2>&1
grep -q "pending" /tmp/setup.log
check "setup lists the pending step" $? "$(tail -2 /tmp/setup.log)"
[ ! -f ~/.walkthrough-secret ]
check "dry run changed nothing" $?

echo "== Step 7 — what the report should be able to say"
python3 - <<'PY'
import json, pathlib, sys
live = json.loads(pathlib.Path.home().joinpath(".claude.json").read_text())
assert "integrated-harness-kit" in live["mcpServers"], live["mcpServers"].keys()
memory = pathlib.Path.home() / "agents" / "shared" / "memory" / "MEMORY.md"
assert memory.is_file(), "memory index not rendered"
print("report inputs available")
PY
check "report inputs available" $?

echo
echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
