# Backlog

Outstanding work for the unified agents harness. Items are listed roughly by
priority within each section.

## Content to fill in (scaffold only today)

- [x] `universal/skills/` — registered 4 existing skills from `~/skills/`:
      `bash-command-style`, `critical-file-safety`, `git-commit-workflow`,
      `safe-file-operations`. All have valid frontmatter and dir name matches
      `name:` field. Discoverable via `~/.claude/skills` and `~/.agents/skills`.
- [x] `shared/mcp/servers.json` — added Linear MCP (remote HTTP, OAuth 2.1).
      `render-mcp.sh` rewritten to handle remote vs stdio per tool: Claude
      `{type:"http",url}`, Codex `url=…`, OpenCode `{type:"remote",…}`,
      Gemini `{httpUrl:…}`. End-to-end run validated.
- [ ] `shared/subagents/` — add sub-agent definitions in the
      claude/opencode-compatible `.md`-with-frontmatter format. Minimum
      common fields: `name`, `description`, `tools`.
- [ ] `shared/commands/` — add custom slash commands as `.md` files.
      Claude/Codex/OpenCode read them directly; run
      `scripts/render-gemini-commands.sh` to also push them into Gemini's
      `.toml` format.
- [ ] `shared/output-styles/` — Claude-only today, but reserved. Add when
      needed.

## Live verification still pending

- [x] `scripts/render-mcp.sh` — executed against Linear MCP. All four tool
      configs verified with correct per-tool field names (`type/url`,
      `httpUrl`, `type:"remote"`, TOML `url=`).
- [ ] `scripts/render-gemini-commands.sh` — never executed. Blocked by empty
      `shared/commands/`.
- [ ] `scripts/install.sh` Phase 3 — logic mirrors the manual restore done
      this session, but no end-to-end live test (would require destroying
      `~/.claude` during a session).
- [ ] Codex `~/.codex/prompts/` → `shared/commands` symlink — confirm Codex
      actually reads `.md` from this path at runtime.
- [ ] Gemini `~/.gemini/GEMINI.md` → `shared/AGENTS.md` symlink — confirm
      Gemini actually loads it as the context file.
- [ ] OpenCode `oh-my-openagent` plugin — confirm it still works after the
      `~/.config/opencode` migration (config + `oh-my-openagent.json`).
- [ ] Memory unification — once a second agent (Codex/OpenCode/Gemini) writes
      to `shared/memory/`, confirm Claude sees the new entries.

## Housekeeping

- [ ] `shared/memory/user_git_identity.md` — decide whether to commit. Holds
      the user's work email; this is a public repo. Either mask the email
      before committing, or keep it in the working tree only (current state).
- [ ] `shared/memory/MEMORY.md` — has one uncommitted line pointing to the
      identity file. Same decision as above.
- [ ] `~/.claude.bak.20260512-183533` and `~/.config/opencode.bak.20260512-183533`
      — remove after ~1 week of stable use (currently they're insurance).
- [ ] `README.md` feature matrix — entry "Persistent memory | OpenCode | via
      AGENTS.md only" is true but understates it: OpenCode also falls back to
      `~/.claude/CLAUDE.md`. Rephrase to reflect both channels.
- [ ] Push to `github.com/tot0rokr/agents` — local has 2 commits ahead of
      origin/main (`0479fd5`, `f06c2df`). Not pushed yet.

## Recommended next step

Pick **one real `SKILL.md` in `universal/skills/`**. It exercises the
multi-tool discovery path end-to-end without needing render scripts, and the
result is immediately observable in any of the four CLIs.
