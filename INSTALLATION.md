# Install the agents harness

This file is meant to be handed to an AI coding agent. Paste it into a fresh session of **Claude Code**, **Codex CLI**, **OpenCode**, or **Gemini CLI** along with a prompt like:

> 이대로 설치해줘

The agent will clone the repo, run the installer, verify it, wire up the `integrated-harness-kit-mcp` entry in your CLI's own config, and ask whether you have private overlay repos to layer on top — you don't need to touch any `settings.json` by hand.

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
      "args": ["--from", "/home/<user>/agents/mcp", "integrated-harness-kit-mcp"]
    }
  }
}
```

Replace `/home/<user>` with the real `$HOME` — these configs do not expand `~` or `$HOME`.

To add by hand: `jq --arg repo "$HOME/agents/mcp" '.mcpServers += {"integrated-harness-kit":{"command":"uvx","args":["--from",$repo,"integrated-harness-kit-mcp"]}}' ~/.claude.json > /tmp/.claude.json.new && mv /tmp/.claude.json.new ~/.claude.json && chmod 600 ~/.claude.json`.

**Codex CLI** (`~/.codex/config.toml`): append (don't replace existing tables):

```toml
[mcp_servers.integrated-harness-kit]
command = "uvx"
args = ["--from", "/home/<user>/agents/mcp", "integrated-harness-kit-mcp"]
```

**OpenCode** (`~/.config/opencode/opencode.json`): set or extend the `mcp` key:

```json
{
  "mcp": {
    "integrated-harness-kit": {
      "type": "local",
      "command": ["uvx", "--from", "/home/<user>/agents/mcp", "integrated-harness-kit-mcp"],
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
      "args": ["--from", "/home/<user>/agents/mcp", "integrated-harness-kit-mcp"]
    }
  }
}
```

> **Note** — the server is installed from the clone you just made, not from PyPI. The published distribution is stale: it predates the overlay-aware tools and declares an unbounded `mcp>=1.0`, so on a machine that resolves `mcp` 2.x today it fails to start. Once a current version is published, `args` becomes just `["integrated-harness-kit-mcp"]`.

Verify the server starts before moving on:

```bash
echo '' | uvx --from ~/agents/mcp integrated-harness-kit-mcp
```

It should exit quietly. A traceback means the entry is not usable yet — report it and stop.

### Step 6 — Ask about overlays

What you have installed so far is the public base: the shared instructions, skills, commands and sub-agents. The parts that describe *this* person and *this* employer — their identity, machine-specific memories, internal MCP servers, credentials — live in private overlay repos layered on top. A machine without them is half set up, and nothing in the base repo can tell you which ones exist.

So ask the user, once:

> Do you have overlay repos for this machine? A personal one, a work one? Paste their git URLs, or say none.

For each URL they give:

```bash
python3 ~/agents/scripts/overlay.py add <alias> <git-url> --priority <N>
python3 ~/agents/scripts/overlay.py install <alias>
```

Use `personal` at priority 50 and `work` at 60 unless the user says otherwise; the higher priority wins where two overlays set the same key. Then check what each one still needs from the machine:

```bash
python3 ~/agents/scripts/overlay.py setup <alias> --dry-run
```

That lists steps an overlay declares beyond files — a credential file to install, a login to perform, a helper to put on PATH. Show the user the list and let them decide; run it with `--yes` only if they say so. Some steps need a secret only they have.

If they say none, say so in your report and move on. `scripts/overlay.py init <alias>` scaffolds a new overlay later, and `docs/overlay.md` explains the model.

### Step 7 — Tell the user what happened

In your final message to the user, include:

1. **Status**: `installed` or `already-installed (only step 5 ran)`.
2. **Backups**: list any `*.bak.<timestamp>` directories created. Mention they're rollback insurance and can be removed after ~1 week of stable use.
3. **Overlays**: which ones were added, which setup steps are still pending, or that the user said there were none.
4. **Restart**: tell them to restart the CLI to pick up the new MCP entry.
5. **Uninstall hint**: to revert, manually restore the `.bak.*` directories and remove the symlinks. (A clean `--uninstall` flow lands later.)

### Error handling rules

- If `git clone` fails (network, auth) — report the exact stderr and stop. Don't retry silently.
- If `python3 install.py` fails — it auto-rolls back. Surface stderr verbatim and stop. The user is not in a broken state.
- If `doctor.sh` fails — surface the failing checks and stop. Don't attempt to fix.
- If your host CLI is none of the four — tell the user, stop. Don't try to install in an unknown shell.
- If `python3` is not available — tell the user to install Python 3.9+ and stop.

### What NOT to do

- Don't modify anything under `~/agents` by hand. Step 5 touches your CLI's own config file; Step 6 goes through `scripts/overlay.py`, which writes only `overlays/` and the rendered artifacts.
- Don't invent overlay URLs, and don't run an overlay's setup steps without the user's word — they execute commands that repo's author wrote.
- Don't run `install.sh` separately — it just shells out to `install.py`.
- Don't ask the user "is it okay if I clone the repo?" — they pasted this document, that *is* the consent. But do report what you did after each step.
