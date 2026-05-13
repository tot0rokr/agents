# Install the agents harness

This file is meant to be handed to an AI coding agent. Paste it into a fresh session of **Claude Code**, **Codex CLI**, **OpenCode**, or **Gemini CLI** along with a prompt like:

> 이대로 설치해줘

The agent will clone the repo, run the installer, verify it, and wire up the `integrated-harness-kit-mcp` entry in your CLI's own config — you don't need to touch any `settings.json` by hand.

If you're a human and want to do it manually instead, just run:

```bash
git clone https://github.com/tot0rokr/agents.git ~/agents
python3 ~/agents/scripts/install.py
bash ~/agents/scripts/doctor.sh
```

---

## For the AI agent

You are an AI coding assistant. The user has handed you this document and asked you to install the agents harness on this machine. Follow every step below in order. Use the tools available to you (Bash, Read, Edit/Write). **Do not improvise** — if a step fails, surface the exact error and stop.

### Step 0 — Detect your host CLI

Figure out which CLI you're running inside. Use this table:

| Signal | Likely host |
|---|---|
| You can call a `Skill` tool, and `/home/$USER/.claude/` exists | Claude Code |
| You see `~/.codex/config.toml` and your tool prefix is `mcp__codex` or you have access to a `codex` shell namespace | Codex CLI |
| You see `~/.config/opencode/opencode.json` | OpenCode |
| You see `~/.gemini/settings.json` and `GEMINI.md` is the context file name | Gemini CLI |

Use Bash to confirm: `ls ~/.claude ~/.codex ~/.config/opencode ~/.gemini 2>/dev/null`. The one that already exists tells you the host.

If you cannot decide, ask the user which CLI they're using and stop. **Do not guess.**

### Step 1 — Check current state

Run:

```bash
test -d ~/agents && echo REPO_EXISTS || echo REPO_MISSING
for p in ~/.claude ~/.codex ~/.config/opencode ~/.gemini ~/.agents; do
  if [ -L "$p" ]; then echo "LINKED  $p -> $(readlink "$p")"
  elif [ -e "$p" ]; then echo "REAL    $p"
  else echo "MISSING $p"; fi
done
```

If `~/agents` already exists and every home path is `LINKED  ... -> .../agents/...`, the harness is already installed. Skip to **Step 4** and just add the MCP entry to your host CLI's config.

### Step 2 — Clone the repo

```bash
git clone https://github.com/tot0rokr/agents.git ~/agents
```

If `~/agents` already exists from a previous attempt and you want a fresh clone, ask the user before doing anything destructive. Don't `rm -rf` without explicit consent.

### Step 3 — Run the installer

```bash
python3 ~/agents/scripts/install.py
```

This is the source of truth for setup. It runs three phases:

1. **Phase 1** — top-level home symlinks. Existing real directories at `~/.claude`, `~/.codex`, `~/.config/opencode`, `~/.gemini`, `~/.agents` are backed up to `<path>.bak.<timestamp>` before being replaced with symlinks into `~/agents/`.
2. **Phase 2** — Claude per-project memory unification. Any pre-existing `~/.claude/projects/<slug>/memory/` is merged into `~/agents/shared/memory/` and replaced with a symlink so all four agents read and write the same memory pool.
3. **Phase 3** — runtime data restore. From the fresh `~/.claude.bak.<timestamp>` the installer copies back credentials, history, sessions, file-history, per-project transcripts, and merges `settings.local.json` permissions.

**Every mutation is tracked. If any step fails, the installer rolls back all completed mutations and exits non-zero.** If the script exits non-zero, report stderr verbatim to the user and stop — do not try to recover by hand.

For dry-run preview, add `--dry-run`. You shouldn't need this unless the user asks.

### Step 4 — Verify

```bash
bash ~/agents/scripts/doctor.sh
```

Expected last line: `doctor: all checks passed`. If anything else, report it to the user and stop.

### Step 5 — Add the `integrated-harness-kit-mcp` entry to your host CLI's config

Use **only** the row for the CLI you detected in Step 0. Use your write/edit tool (not heredoc-echo) and merge with existing config — preserve all current keys.

**Claude Code** (`~/.claude.json` — **NOT** `~/.claude/settings.json`; Claude Code reads MCP servers from the home-level file). The file is large (~30 KB of runtime state); use a jq merge or a careful edit, **preserve all existing keys**. Set or extend `mcpServers`:

```json
{
  "mcpServers": {
    "integrated-harness-kit": {
      "command": "uvx",
      "args": ["integrated-harness-kit-mcp"]
    }
  }
}
```

If `~/agents/scripts/render-mcp.sh` ran during install, this is already patched for you — verify with `jq '.mcpServers' ~/.claude.json`. To add by hand: `jq '.mcpServers += {"integrated-harness-kit":{"command":"uvx","args":["integrated-harness-kit-mcp"]}}' ~/.claude.json > /tmp/.claude.json.new && mv /tmp/.claude.json.new ~/.claude.json && chmod 600 ~/.claude.json`.

**Codex CLI** (`~/.codex/config.toml`): append (don't replace existing tables):

```toml
[mcp_servers.integrated-harness-kit]
command = "uvx"
args = ["integrated-harness-kit-mcp"]
```

**OpenCode** (`~/.config/opencode/opencode.json`): set or extend the `mcp` key:

```json
{
  "mcp": {
    "integrated-harness-kit": {
      "type": "local",
      "command": ["uvx", "integrated-harness-kit-mcp"],
      "enabled": true
    }
  }
}
```

**Gemini CLI** (`~/.gemini/settings.json`): set or extend `mcpServers`:

```json
{
  "mcpServers": {
    "integrated-harness-kit": {
      "command": "uvx",
      "args": ["integrated-harness-kit-mcp"]
    }
  }
}
```

> **Note** — `integrated-harness-kit-mcp` is the PyPI distribution of the MCP server. If `uvx` reports "package not found", the latest tag may not have been pushed to PyPI yet; clone the repo and use `uvx --from /path/to/agents/mcp integrated-harness-kit-mcp` as a local fallback.

### Step 6 — Tell the user what happened

In your final message to the user, include:

1. **Status**: `installed` or `already-installed (only step 5 ran)`.
2. **Backups**: list any `*.bak.<timestamp>` directories created. Mention they're rollback insurance and can be removed after ~1 week of stable use.
3. **Restart**: tell them to restart the CLI to pick up the new MCP entry. If `uvx` reports "package not found", the maintainer hasn't pushed the latest tag to PyPI; use the local-fallback snippet from the Note above.
4. **Uninstall hint**: to revert, manually restore the `.bak.*` directories and remove the symlinks. (A clean `--uninstall` flow lands later.)

### Error handling rules

- If `git clone` fails (network, auth) — report the exact stderr and stop. Don't retry silently.
- If `python3 install.py` fails — it auto-rolls back. Surface stderr verbatim and stop. The user is not in a broken state.
- If `doctor.sh` fails — surface the failing checks and stop. Don't attempt to fix.
- If your host CLI is none of the four — tell the user, stop. Don't try to install in an unknown shell.
- If `python3` is not available — tell the user to install Python 3.9+ and stop.

### What NOT to do

- Don't modify any file under `~/agents` other than the one config file from Step 5.
- Don't run `install.sh` separately — it just shells out to `install.py`.
- Don't ask the user "is it okay if I clone the repo?" — they pasted this document, that *is* the consent. But do report what you did after each step.
