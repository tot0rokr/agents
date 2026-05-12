# Backlog

Outstanding work for the unified agents harness. Items are roughly priority-ordered within each section. Tick when done so the file stays trustworthy.

## Content to fill in

- [x] `universal/skills/` — registered 4 existing skills from `~/skills/`:
      `bash-command-style`, `critical-file-safety`, `git-commit-workflow`,
      `safe-file-operations`. Discoverable via `~/.claude/skills` and
      `~/.agents/skills`.
- [x] `shared/mcp/servers.json` — Linear MCP (remote HTTP, OAuth 2.1).
      `render-mcp.sh` handles remote vs stdio per tool.
- [x] `shared/subagents/` — 3 sub-agents (Claude + OpenCode shared):
      `code-reviewer`, `agents-harness-auditor`, `linear-triage`.
      Codex/Gemini sub-agents would need separate render scripts; deferred.
- [x] `shared/commands/` — 3 commands: `/commit`, `/review`, `/audit`.
      Claude/Codex/OpenCode read `.md` directly; Gemini gets `.toml`
      via `render-gemini-commands.sh`.
- [ ] `shared/output-styles/` — Claude-only feature today. Add when needed.

## Live verification

- [x] `scripts/render-mcp.sh` — 4 tools render correctly; idempotent on
      re-run; preserves Codex CLI-written sections like `[projects."<path>"]`.
- [x] `scripts/render-gemini-commands.sh` — 3 commands rendered to TOML.
- [x] OpenCode `oh-my-openagent` plugin — confirmed working after the
      `~/.config/opencode` symlink swap: it auto-migrated its config
      (model bumps + fallback entries) on first run.
- [x] Codex CLI reads `~/.codex/config.toml` — confirmed via Codex
      writing its own sections (`[tui.model_availability_nux]`,
      `[projects."/home/junho"]`) to the file.
- [ ] Codex `~/.codex/prompts/*.md` actually loaded as slash commands —
      symlink exists and files are visible, but not yet exercised in a
      live Codex session.
- [ ] Gemini `~/.gemini/GEMINI.md` actually loaded as the context file —
      symlink exists, doctor.sh passes, but no live Gemini session yet.
- [ ] Memory unification across agents — once a second agent
      (Codex/OpenCode/Gemini) writes to `shared/memory/`, confirm Claude
      auto-memory sees the new entry.
- [ ] `scripts/install.sh` Phase 3 — logic mirrors the manual restore done
      this session, but no end-to-end live test (would require destroying
      `~/.claude` mid-session).

## Housekeeping

- [ ] `shared/memory/user_git_identity.md` + the matching line in
      `shared/memory/MEMORY.md` — still uncommitted. Holds the user's
      work email; this is a public repo. Decide: mask the email and
      commit, or keep working-tree only forever.
- [ ] `~/.claude.bak.20260512-183533` and
      `~/.config/opencode.bak.20260512-183533` — remove after ~1 week of
      stable use (currently retained as rollback insurance).
- [ ] `doctor.sh` improvement: validate every `universal/skills/*/SKILL.md`
      has a `name:` matching its directory name. Catches the most common
      Claude-discovery mistake.
- [ ] `doctor.sh` improvement: run each `render-*.sh` against `mktemp`
      copies and diff against the in-tree file. Flags render drift before
      it lands in a commit.
