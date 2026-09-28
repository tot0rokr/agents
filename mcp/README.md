# integrated-harness-kit-mcp

An MCP server for managing the [`tot0rokr/agents`](https://github.com/tot0rokr/agents) harness — the shared configuration layer behind **Claude Code**, **Codex CLI**, **OpenCode** and **Gemini CLI** — from inside a chat.

## Install

```bash
uvx integrated-harness-kit-mcp
```

That runs the server on stdio; pair it with a CLI agent's MCP client (the repo root's `INSTALLATION.md` has per-CLI config snippets).

## What it understands

The harness has three kinds of file, and every tool tells them apart before reading, writing or staging anything:

| Kind | Examples | Writes | Commits |
|---|---|---|---|
| base source | `claude/settings.base.json`, `shared/commands/`, `universal/skills/` | direct | yes |
| artifact | `claude/settings.json`, `shared/mcp/servers.json`, `shared/memory/MEMORY.md` | render only | never |
| overlay-owned | anything symlinked out of `overlays/<alias>/` | in the overlay | in the overlay's own repo |

Overlays are private repos layered onto the public base — one per environment, carrying that environment's memories, instructions, MCP servers and credentials. A tool that ignored the distinction would either lose work on the next render or commit an employer's internal hostnames to a public repo.

## Tools

### Diagnostics

| Tool | Purpose |
|---|---|
| `status(level)` | repo, home symlinks, artifacts, overlays; `level="full"` also runs `doctor.sh` |
| `capabilities()` | what the repo on this machine supports, so an old repo degrades instead of failing |
| `audit_drift()` | classify every uncommitted change here and in each overlay |

### Reading

| Tool | Purpose |
|---|---|
| `list_content(kind)` | skills, commands, subagents, memory, instructions — each with its source |
| `list_mcp_servers(scope)` | `effective`, `base`, or `both`; never returns `env` or `headers` |
| `settings_get(key)` | effective settings with per-key provenance: base, overlay:*, or runtime |
| `overlay_list()` | registered overlays, priority, link count, cleanliness |
| `overlay_route(path)` | which overlay owns a piece of work, for session logs and journals |

### Writing

| Tool | Purpose |
|---|---|
| `scaffold(kind, name, target)` | new content in the base or in an overlay; refuses a name another overlay supplies |
| `remove_content(kind, name)` | delete base content; refuses overlay-owned paths |
| `settings_set(key, value, target)` | write the source that owns the key, then re-render |
| `mcp_server_set` / `mcp_server_remove` | server definitions; credentials only in an overlay |

### Lifecycle

| Tool | Purpose |
|---|---|
| `bootstrap()` | clone, install, render, apply overlays, verify |
| `update()` | pull, re-render, re-apply overlays, doctor |
| `render(scope)` | `artifacts`, `public`, `local` — see below |
| `overlay_add` / `overlay_install` / `overlay_remove` | overlay lifecycle |
| `overlay_setup(alias, yes)` | an overlay's environment setup steps; dry run unless `yes=True` |
| `commit(paths, message)` | explicit-path commit, never `git add -A` |
| `overlay_commit(alias, message)` | the same, inside an overlay's repo |

## Render scopes

`servers.json` merges private overlays into a file the per-tool configs are generated from, and those configs are tracked in a public repo. So rendering is split by audience:

- `artifacts` — `settings.json`, `servers.json`, `MEMORY.md`. Untracked, base plus overlays.
- `public` — `codex/config.toml`, `gemini/settings.json`, `opencode/opencode.json`. Tracked here, so rendered from `servers.base.json` only, with a check afterwards that no overlay-only server reached them.
- `local` — `~/.claude.json`. This machine, base plus overlays, merging each server's `env` and `headers` so a password that exists only here is not wiped.

## Repo discovery

1. the tool's `repo_path` argument
2. `$AGENTS_REPO`
3. `~/agents`

A candidate is accepted only if it contains `scripts/install.py`.

## Development

```bash
cd mcp/
python3 -m venv .venv
.venv/bin/pip install -e '.'
.venv/bin/python -m unittest discover -s tests -v
```

Tools live in `src/integrated_harness_kit_mcp/tools/` as plain functions, so the tests neither import `mcp` nor depend on FastMCP. The fixtures build a throwaway repo carrying the harness's *real* `scripts/` and real overlays, so the overlay, render and commit tests exercise the same code a machine runs rather than a mock of it.

## License

MIT. See repo root.
