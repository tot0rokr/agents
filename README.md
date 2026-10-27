# agents

Unified configuration for four CLI coding agents — **Claude Code**, **Codex
CLI**, **OpenCode**, **Gemini CLI** — sharing a single source of truth where
possible and falling back to per-tool files where formats differ.

## Layout

```
agents/
├── universal/                 -> ~/.agents       (codex/opencode/gemini fallback)
│   └── skills/                  canonical SKILL.md location (3 tools auto-discover)
│
├── shared/                      cross-tool content (not exposed at ~/.agents)
│   ├── AGENTS.md                main instruction file, referenced by all 4
│   ├── instructions/            topic files linked from AGENTS.md
│   ├── memory/                  long-term memory; OpenCode reads via AGENTS.md ref
│   ├── memory/MEMORY.base.md    tracked base for the memory index
│   ├── memory/MEMORY.md         rendered from base + overlays (gitignored)
│   ├── mcp/servers.base.json    tracked base for MCP definitions
│   ├── mcp/servers.json         rendered from base + overlays (gitignored)
│   ├── subagents/               .md frontmatter (claude/opencode direct)
│   ├── commands/                .md (claude/codex/opencode direct; gemini rendered)
│   └── output-styles/           Claude-specific today, reserved for future
│
├── claude/                    -> ~/.claude
│   ├── CLAUDE.md                -> ../shared/AGENTS.md
│   ├── settings.base.json       tracked base: hooks, permissions, model
│   ├── settings.json            rendered from base + overlays (gitignored)
│   ├── global-config.base.json  tracked: options Claude Code reads only from ~/.claude.json
│   ├── skills/                  -> ../universal/skills
│   ├── agents/                  -> ../shared/subagents
│   ├── commands/                -> ../shared/commands
│   ├── memory/                  -> ../shared/memory
│   └── output-styles/           -> ../shared/output-styles
│
├── codex/                     -> ~/.codex
│   ├── AGENTS.md                -> ../shared/AGENTS.md
│   ├── AGENTS.override.md       AGENTS.md with instructions/*.md inlined; Codex reads it first (gitignored)
│   ├── config.base.toml         tracked base for config.toml
│   ├── config.toml              rendered from base + MCP servers + overlays; Codex writes here too (gitignored)
│   └── prompts/                 -> ../shared/commands  (Codex reads .md natively)
│
├── opencode/                  -> ~/.config/opencode
│   ├── AGENTS.md                -> ../shared/AGENTS.md
│   ├── opencode.json            MCP, LSP, formatter, TUI
│   ├── agents/                  -> ../shared/subagents
│   ├── commands/                -> ../shared/commands
│   └── plugins/                 JS/TS hooks (OpenCode-specific)
│
├── gemini/                    -> ~/.gemini
│   ├── GEMINI.md                -> ../shared/AGENTS.md
│   ├── settings.json            MCP, hooks, agents
│   ├── commands/                .toml files generated from shared/commands
│   └── extensions/              Gemini Extensions
│
├── scripts/
│   ├── install.py               home-dir symlinks, rollback-safe; renders settings
│   ├── install.sh               thin wrapper around install.py
│   ├── overlay.py               register and apply environment overlays
│   ├── render_settings.py       bases + overlays -> every render artifact, Codex's included
│   ├── render-mcp.sh            servers.json -> ~/.claude.json; servers.base.json -> OpenCode, Gemini
│   ├── render-codex-config.sh   wrapper around render_settings.py
│   ├── render-gemini-commands.sh   shared/commands/*.md -> gemini/commands/*.toml
│   ├── render-gemini-settings.sh   wrapper around render-mcp.sh
│   └── doctor.sh                verify links and configs
│
├── templates/overlay-example/   skeleton for a new overlay repo
├── docs/overlay.md              how overlays work
└── overlays/                    overlay clones and local state (gitignored)
```

## Quick start

```bash
git clone <this repo> ~/agents
cd ~/agents
./scripts/doctor.sh              # verify internal layout
./scripts/install.sh --dry-run   # preview home-dir symlinks
./scripts/install.sh             # actually install
```

Existing real directories at the target paths are backed up to
`<path>.bak.<timestamp>` before being replaced. Existing symlinks that already
point at this repo are skipped.

## Editing memory and instructions

| Edit this | Effect |
|---|---|
| `shared/AGENTS.md` | All 4 tools (via their instruction-file symlinks; Codex via the rendered `codex/AGENTS.override.md`). |
| `shared/instructions/*.md` | Linked from AGENTS.md. Only Codex gets them as instructions: `render_settings.py` inlines them into `codex/AGENTS.override.md`. Claude Code loads `@path` imports, not plain links, so it sees the link line and reads the file only when the agent opens it; see BACKLOG. |
| `shared/memory/<name>.md` | Listed in the index; all 4 see it. |
| `shared/memory/MEMORY.base.md` | The tracked index. Rendered into `MEMORY.md`, which AGENTS.md references. |
| `universal/skills/<name>/SKILL.md` | All 4 tools (Codex/OpenCode/Gemini via `~/.agents/skills`, Claude via `~/.claude/skills` symlink). |
| `shared/subagents/<name>.md` | Claude and OpenCode directly. Codex/Gemini need their own format. |
| `shared/commands/<name>.md` | Claude, Codex (`~/.codex/prompts/`), OpenCode directly. Run `render-gemini-commands.sh` to push to Gemini. |
| `shared/mcp/servers.base.json` | Canonical. Run `render_settings.py` (it renders `servers.json` and Codex's config), then `render-mcp.sh` (Claude's `~/.claude.json` from `servers.json`, OpenCode and Gemini from the base). |

## Overlays

This repo is public, so nothing environment-specific belongs in it — no employer hostnames, internal remotes, project names, IPs, ports or account IDs. Those live in a separate overlay repo (private for a real environment) that is layered on top at install time.

```bash
scripts/overlay.py init work                 # scaffolds overlays/work from the template
scripts/overlay.py add work --priority 60    # register what is already at overlays/work
scripts/overlay.py add work <git-url>        # or clone it there first, on another machine
scripts/overlay.py install work              # symlink content, re-render settings and MCP
scripts/overlay.py setup work --dry-run      # what still needs setting up by hand or by agent
scripts/overlay.py route --explain           # which overlay owns the work in this directory
scripts/overlay.py status                    # drift check
```

Overlays live at `overlays/<alias>` inside this repo, and `overlays/` is gitignored in full, so a private overlay sits next to the base tree without the base ever tracking it.

An overlay contributes memory, instructions, commands, sub-agents and skills as symlinks, merges `settings/claude.json`, `settings/codex.toml` and `mcp/servers.json` into their rendered counterparts, and can symlink anything else through a `links` map in its manifest. Multiple overlays coexist; `priority` decides who wins on a shared key.

Because Claude Code writes runtime state into `~/.claude/settings.json` — which is this repo's `claude/settings.json` — that file, `shared/mcp/servers.json` and the memory index `shared/memory/MEMORY.md` are render artifacts and are not tracked. Codex is in the same position: it writes trusted project paths into `~/.codex/config.toml`, so `codex/config.toml` is rendered too, and gets the overlays' MCP servers along with it. Edit `claude/settings.base.json`, `codex/config.base.toml`, `shared/mcp/servers.base.json` or `shared/memory/MEMORY.base.md` for anything that should be public and shared, or an overlay for anything that should not. A memory an agent writes stays untracked until it is filed into one or the other. Full design in [docs/overlay.md](docs/overlay.md).

## Adding new content

Most additions are zero-build — drop a file in the canonical location and all four tools see it. MCP servers and Gemini slash commands are the two exceptions; they go through render scripts because the per-tool formats diverge.

### A new MCP server

Edit `shared/mcp/servers.base.json` (or an overlay's `mcp/servers.json` for a private one), then run `scripts/render_settings.py` and `scripts/render-mcp.sh`. The schema accepts both remote HTTP/SSE servers and local stdio servers; the renderers pick the right per-tool format from the fields you set. Codex has no SSE transport, so an SSE server is left out of its config with a warning.

```json
{
  "servers": {
    "linear": {
      "description": "Linear — issues, projects",
      "url": "https://mcp.linear.app/mcp",
      "transport": "http"
    },
    "filesystem": {
      "description": "Local filesystem access",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/junho"]
    }
  }
}
```

`url` → remote (`transport` defaults to `http`; set `"sse"` for SSE). `command` → stdio.

After rendering, commit the canonical source together with the two regenerated tool configs that are tracked, `gemini/settings.json` and `opencode/opencode.json`. OAuth-based servers (Linear, GitHub, etc.) prompt for authorization the first time a tool needs them; tokens are cached per-tool, never in this repo.

### A new skill

Drop a directory under `universal/skills/<name>/` containing `SKILL.md`. Frontmatter requires `name` (must match the directory) and `description`.

```
universal/skills/<name>/SKILL.md
```

```markdown
---
name: <name>
description: One-sentence trigger description — agents read this to decide when the skill applies.
---

Body of the skill: what to do, what not to do.
```

All four tools auto-discover. No render step.

### A new sub-agent

Drop `shared/subagents/<name>.md` with `name` + `description` frontmatter and the system prompt as the body. Claude (`~/.claude/agents/`) and OpenCode (`~/.config/opencode/agents/`) read it directly via the install-time symlinks. Codex and Gemini don't read `.md` sub-agents and would need their own render script — not implemented.

### A new slash command

Drop `shared/commands/<name>.md` with `description` frontmatter. Use `$ARGUMENTS` to access whatever the user typed after the command.

```markdown
---
description: <one-line summary shown in /help>
---

Prompt body, possibly multi-step. End with: $ARGUMENTS
```

Claude, Codex (`~/.codex/prompts/`), and OpenCode all read these `.md` files directly. To push to Gemini (which only accepts TOML), run `scripts/render-gemini-commands.sh`. Commit the generated `gemini/commands/<name>.toml` alongside the source.

## When to run render scripts

| Edited | Run |
|---|---|
| `shared/mcp/servers.base.json` | `scripts/render_settings.py` (Codex is one of its outputs), then `scripts/render-mcp.sh` |
| `codex/config.base.toml`, an overlay's `settings/codex.toml` | `scripts/render_settings.py` |
| `shared/memory/MEMORY.base.md` | `scripts/render_settings.py` |
| `shared/commands/*.md` | `scripts/render-gemini-commands.sh` (only Gemini needs it) |
| `shared/AGENTS.md`, `shared/instructions/*.md` | `scripts/render_settings.py` for Codex, which reads `codex/AGENTS.override.md`; the other tools read `AGENTS.md` live through their symlinks, and an instruction file only when the agent opens it. |
| `shared/memory/*.md` | Nothing — symlinks pick up changes live. |
| `universal/skills/*/SKILL.md` | Nothing — auto-discovered live. |
| `shared/subagents/*.md` | Nothing — symlinks pick up changes live (Claude / OpenCode). |

Render scripts are idempotent and preserve user-meaningful sections of each tool's config. `render_settings.py` keeps every key Codex wrote into `codex/config.toml` that no source names — trusted projects, UI counters — and leaves a file untouched when its data already matches, so a running session's file watcher is not woken for nothing.

## Hooks

Hook schemas don't share well across tools (event names and payload formats
differ), so hooks live inside each tool's native config:

- Claude: `claude/settings.json` `.hooks`
- Codex: `[hooks]` in `codex/config.base.toml` or an overlay's `settings/codex.toml`, or `codex/hooks.json`
- OpenCode: `opencode/plugins/*.{ts,js}` (event-handler modules)
- Gemini: `gemini/settings.json` `.hooks`

## Feature support matrix

| Feature | Claude | Codex | OpenCode | Gemini |
|---|---|---|---|---|
| Skills (SKILL.md) | yes | yes | yes | yes |
| Hooks | yes | yes | yes (plugins) | yes |
| Persistent memory | yes (auto-memory) | yes (`[features] memories`; writes its own `~/.codex/memories/`, reads `shared/memory` via AGENTS.md) | via AGENTS.md + CLAUDE.md fallback | yes (save_memory) |
| Sub-agents | yes | yes | yes | yes |
| Custom slash commands | yes | yes | yes | yes (TOML format) |
| MCP servers | yes | yes | yes | yes |
| Plugins / Extensions | yes | yes | yes | yes |
| Output styles | yes (persona) | TUI only | themes only | themes only |

## Troubleshooting

`scripts/doctor.sh` is the first stop. It walks every internal symlink, parses every JSON/TOML config, and verifies the home-dir symlinks (if `install.sh` has run). A clean run prints `doctor: all checks passed`.

Common gotchas:

- **`/resume` in Claude Code shows no conversations** — Claude organises transcripts per cwd at `~/.claude/projects/<slug-of-cwd>/*.jsonl`. If you launched Claude from a different directory than where the conversations live, switch cwd and try again. `install.sh` Phase 2 creates a memory symlink under each slug that exists at install time (plus the one for the directory it runs from), so the memory pool is shared even though the transcripts aren't. A project first opened after the install gets its own `memory/` directory, which is not shared and stays on that machine; re-run the installer to link it.

- **A tool config keeps drifting after every CLI run** — some tools mutate their own config: OpenCode's `oh-my-openagent` plugin drops timestamped backup files, which are in `.gitignore`. Codex writes into `codex/config.toml` all the time, but that file is untracked, so it no longer shows up in `git status`. New drift you can't kill? Add the offending section/pattern to the matching ignore list.

- **A setting changed inside Codex snaps back** — every key in `codex/config.base.toml` (or an overlay's `settings/codex.toml`) is enforced on each render, `model` and `service_tier` included, and so is the transport of an MCP server the sources define, so re-adding one with `codex mcp add` and the other transport is undone. Change the source instead; `overlay.py status` reports the difference as DRIFT until then.

- **A render script's output looks wrong** — its source is `shared/mcp/servers.base.json` plus each overlay's `mcp/servers.json` (or `shared/commands/`, or `codex/config.base.toml`). Edit the canonical source, never the rendered file. Re-running render is non-destructive: what Codex wrote for itself, like `[projects."<path>"]`, survives.

- **Linear / GitHub / Notion MCP says "not authenticated"** — expected on first use. Each tool runs its own OAuth flow on first request (browser opens, you approve). Tokens cache per-tool, never shared. Re-auth required if you revoke or switch workspaces.

- **`install.sh` complains about an existing target** — it backs the existing directory up to `<target>.bak.<timestamp>` before symlinking. Inspect that backup if anything important was inside. Phase 3 then restores runtime data (credentials, sessions, transcripts, `file-history/`, `settings.local.json` permissions) so re-login is usually unnecessary.

## Updating

```bash
cd ~/agents
git pull
scripts/render_settings.py        # render artifacts, Codex's config and instructions included
scripts/render-mcp.sh             # if shared/mcp/servers.base.json changed upstream
scripts/render-gemini-commands.sh # if shared/commands/ changed upstream
scripts/doctor.sh                 # sanity check
```

One pull needs care: the one that stopped tracking `codex/config.toml`. Where Codex has written to the file since it was last committed — the usual case — git refuses that pull ("Your local changes to the following files would be overwritten by merge"); where it has not, git deletes the file. Run this in place of the plain `git pull`, while no Codex session is running. It keeps what Codex wrote there (trusted projects, servers added with `codex mcp add`, feature flags) whether the pull fast-forwards, merges or rebases:

```bash
cd ~/agents
cp -p codex/config.toml codex/config.toml.bak.migrate && git checkout HEAD -- codex/config.toml
git pull
cp -p codex/config.toml.bak.migrate codex/config.toml
scripts/render_settings.py
```

The second line sets Codex's copy aside and resets the tracked one, so the pull goes through; the fourth puts the copy back even when the pull fails, so the block can be run again once the pull is sorted out.

- **Pulled already, and git deleted the file:** the first render after that pull (`scripts/render_settings.py` or `install.sh`) restores the copy the checkout had, from the reflog or `ORIG_HEAD`. `doctor.sh` says so, with a `git show` command for a checkout where git no longer has it.
- **Through the MCP `update` tool:** it runs `git pull --ff-only`, so where Codex has changed the file it stops at that pull, as a plain `git pull` does, and loses nothing; run the block above then. Where the file is unmodified the pull deletes it and the render restores it, as described above.
- **Stashed, as git suggested:** `git stash pop` stops on a conflict over this file and leaves Codex's copy in place. `git rm --cached codex/config.toml && git stash drop` resolves it.
- **Codex's changes committed here and not pushed:** the pull itself stops on that conflict, and the block still puts Codex's copy back. `git rm --cached codex/config.toml`, finish with `git commit` (merge) or `git rebase --continue` (rebase), then render. Before the next push, `git log --stat @{u}..` shows whether a commit of yours still carries `codex/config.toml`; it can hold tokens (`codex mcp add --env`), so do not push one that does.
- **Once Codex starts fine, delete `codex/config.toml.bak.migrate`.** git ignores it, but it is a copy of a file that can hold tokens.
- **Afterwards, in `~/agents` itself, do not check out, reset to or rebase onto a commit from before that pull.** git treats the now-ignored file as disposable: it overwrites it with the old tracked copy, and deletes it on the way back. Look at old commits in a separate worktree (`git worktree add ../agents-old <commit>`), or use `git checkout --no-overwrite-ignore`, which refuses instead.

`install.sh` does not need to re-run on a routine pull — the home-dir symlinks already point at the repo, so anything you pull is immediately live in all four CLIs.
