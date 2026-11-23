# Backlog

Outstanding work for the unified agents harness and its companion MCP package. Items are roughly priority-ordered within each section. Tick when done so the file stays trustworthy.

## Content to fill in

- [x] `universal/skills/` — the canonical skill location, filled by the base and by every enabled overlay. Discoverable via `~/.claude/skills` and `~/.agents/skills`.
- [x] `base/mcp/servers.json` — Linear MCP (remote HTTP, OAuth 2.1).
      `render-mcp.sh` and, for Codex, `render_settings.py` handle remote vs
      stdio per tool.
- [x] `shared/subagents/` — 3 sub-agents (Claude + OpenCode shared):
      `code-reviewer`, `agents-harness-auditor`, `linear-triage`.
      Codex/Gemini variants would need separate render scripts; deferred.
- [x] `shared/commands/` — `/commit`, `/review`, `/audit`. Claude/Codex/
      OpenCode read `.md` directly; Gemini gets `.toml` via
      `render-gemini-commands.sh`.
- [ ] `shared/output-styles/` — Claude-only feature today. Add when needed.
- [ ] Floor-guard skill (adapted from addyosmani/agent-skills
      `constraint-driven-development`): a diff-scoped check that flags
      weakened quality bars — new `NOLINT`, `#pragma GCC diagnostic ignored`,
      `-Wno-*`, `cppcheck-suppress`, `shellcheck disable`, `INSANE_SKIP`,
      `ERROR_QA` → `WARN_QA`, dropped `-Werror`; `eslint-disable`,
      `@ts-ignore`, `@ts-expect-error`, `# noqa`, `# type: ignore`, loosened
      `tsconfig` strictness; skipped, focused (`.only`) or deleted tests,
      removed assertions. Python script with exit codes 0 clean / 1 violation /
      2 could not run ("never let a 2 read as a 0"); tests in Docker.
- [ ] Korean-aware trigger evals for `universal/skills`: positive and
      owner-negative prompts per skill, description collision check. The
      upstream agent-skills Tier 2 tokenizer strips Hangul, so it can't be
      reused as is.

## Live verification

- [x] `scripts/render-mcp.sh` — Claude, OpenCode and Gemini render
      correctly; idempotent on re-run. Codex moved to
      `render_settings.py`, which preserves Codex CLI-written sections like
      `[projects."<path>"]`.
- [x] `scripts/render-gemini-commands.sh` — 3 commands rendered to TOML.
- [x] OpenCode `oh-my-openagent` plugin — confirmed working after the
      `~/.config/opencode` symlink swap (auto-migrated config on first run).
- [x] Codex CLI reads `~/.codex/config.toml` — confirmed via Codex
      writing its own sections to the file.
- [x] `scripts/install.py` rollback path — covered by `test_install.py`
      injection tests (`test_state_restored_after_failure`,
      `test_clean_install_works_after_rollback`). Real-system
      destroy-and-rollback test still pending; would require detonating
      `~/.claude` mid-session.
- [ ] Codex `~/.codex/prompts/*.md` actually picked up as slash
      commands — symlink exists and files are visible, but not exercised
      in a live Codex session yet.
- [ ] Gemini `~/.gemini/GEMINI.md` actually loaded as the context file —
      symlink exists, doctor.sh passes, but no live Gemini session yet.
- [ ] Memory unification across agents — once a second agent
      (Codex/OpenCode/Gemini) writes to `shared/memory/`, confirm Claude
      auto-memory sees the new entry.

## integrated-harness-kit-mcp roadmap

- [x] **v0.1.0** — `scripts/install.py` (Python rewrite of install.sh
      with operation-level rollback), `INSTALLATION.md` (agent-readable
      bootstrap recipe), 8 unittest cases.
- [x] **v0.2.0** — `mcp/` package (publishable PyPI module
      `integrated-harness-kit-mcp`). Read-only tools: `harness_status`,
      `doctor`, `list_skills`, `list_mcp_servers`, `list_commands`,
      `list_subagents`. 14 unittest cases.
- [x] **v0.3.0** — mutate tools: `clone`, `install`, `render`. 11
      unittest cases including a real-install-against-fake-home E2E.
      Total package coverage: 33 cases.
- [x] **v0.3.1** — pre-publish rename `harness-adapter-mcp` ->
      `integrated-harness-kit-mcp`. Published on TestPyPI and PyPI.
      `git-commit-workflow` skill also tightened (mandate `git status`/`git
      diff` before staging, forbid `git add -A`) after a near-miss leak.
- [x] **v0.4.0** — content tools: `add_skill` / `remove_skill`,
      `add_mcp_server` / `remove_mcp_server`,
      `add_command` / `remove_command`,
      `add_subagent` / `remove_subagent`. Each `add_*` triggers the
      matching render where applicable; remove_* the inverse. 22 unittest
      cases; total package coverage: 55 cases.
- [x] **v1.0.0** — caught the package up with the overlay split, and pruned it while doing so. New `layout.py` classifies every path as base source, render artifact or overlay-owned, and `repo_scripts.py` loads the repo's own `overlay.py` / `render_settings.py` instead of duplicating them. Redundant tools were merged: `harness_status`+`doctor` into `status(level)`, three listers into `list_content(kind)`, eight `add_*`/`remove_*` into `scaffold`/`remove_content`, `clone`+`install` into `bootstrap`. New: `capabilities`, `settings_get`/`settings_set` with per-key provenance, `mcp_server_set`/`mcp_server_remove`, the `overlay_*` family including `overlay_route` and `overlay_commit`, and the v0.5 maintenance set (`update`, `audit_drift`, `commit`) finally registered. `render` gained scopes so the public per-tool configs are rendered from base only. 127 unittest cases against a fixture repo that carries the real scripts and real overlays.
- [ ] **v1.1** — `edit_memory` / `edit_instruction`. A file in `shared/memory/` may belong to an overlay: a symlink into `overlays/<alias>/`, or a real file a checkout overlay tracks in place. Writing it silently edits that overlay's repo, so the tool must find the owner first (`layout.applied_owner`), say which repo it dirtied, and refuse unless the caller named the overlay.

## Overlays

- [x] Overlay mechanism — `docs/overlay.md`, `scripts/overlay.py` (add/install/list/status/update/remove/init), `scripts/render_settings.py`, `templates/overlay-example/`. Markdown and skill drop-ins are symlinked from the overlay clone, JSON fragments are deep-merged, arbitrary paths go through the manifest's `links` map, `${VAR}` comes from the overlay's `vars.json`, and applied state lives in `overlays/*.local.json`.
- [x] `claude/settings.json` and `shared/mcp/servers.json` are render artifacts and untracked — Claude Code writes `autoMode.environment` (employer hostnames, repo paths) straight into the settings file, which used to land in a public repo's staging area.
- [x] Environment-specific content moved out of the base repo into private overlays: the `~/worklog` hooks, memories naming machines or an employer, and a home path in a README example. `shared/AGENTS.md` says where new content goes, and a pre-commit hook refuses a base commit of a path an overlay provides.
- [ ] Publish `agents-overlay-example` as its own public repo, and teach `overlay.py init` to start from a git URL as well as the in-tree template.
- [x] Overlay tools in `integrated-harness-kit-mcp` — shipped in v1.0.0: `overlay_add` / `overlay_install` / `overlay_remove` / `overlay_setup` / `overlay_route` / `overlay_commit`, with overlay state folded into `status` and `audit_drift`.
- [x] Setup steps — an overlay declares what its environment needs beyond files (credential files, daemons, logins) as `check` / `run` / `agent` / `manual` entries, and `overlay.py setup` works through them. Agent steps go to `claude -p` with a narrowed tool list and a guardrail prompt, or to a live session with `--interactive`. Nothing runs without `--yes`.
- [x] `overlay.py` unit tests — `scripts/test_layers.py` and `scripts/test_render_codex.py` cover init, add, install, setup, status, remove, convert and file against fixture repos.
- [ ] `overlay.py update` has a single test (a symlink overlay whose upstream moved to the checkout layout stops and asks for `convert`); the plain fast-forward and a dirty clone are untested.
- [x] `render-mcp.sh` used to replace `~/.claude.json`'s `mcpServers` wholesale, dropping a value that existed only on that machine and any server registered there by hand. It now merges per server, with the canonical source winning the keys it defines.
- [x] `render-mcp.sh` is safe to run by hand again. It reads two sources now: the tracked per-tool configs come from `base/mcp/servers.json`, and only `~/.claude.json` gets the overlay-merged set. `doctor.sh` fails if an overlay-only server ever appears in one of the tracked files, so the guarantee is checked rather than assumed.
- [x] Memory pointer lines have an overlay path. `shared/memory/MEMORY.md` is rendered from the tracked `base/memory/MEMORY.md` plus each overlay's `memory/MEMORY.md` fragment, and lines agents append at runtime are carried over.
- [x] Codex gets the same split. `codex/config.toml` is rendered from `base/settings/codex.toml`, the overlay-merged MCP servers and each overlay's `settings/codex.toml`, keeps what Codex writes for itself, and is untracked with mode 600. `codex/AGENTS.override.md` inlines the instruction files `AGENTS.md` only links to, since Codex does not follow links.
- [ ] Gemini and OpenCode configs are still tracked and base-only, so neither gets overlay MCP servers. Same split as Codex.
- [ ] `settings_get` / `settings_set` in the MCP package only know Claude's settings; teach them `base/settings/codex.toml` and `settings/codex.toml`.
- [ ] The MCP server mapping exists three times: jq in `render-mcp.sh`, Python in `render_settings.codex_mcp_servers`, and Python again in the MCP package's local render. Fold them into one.
- [ ] Claude Code also loads only `@path` imports, not plain links, so `shared/AGENTS.md`'s `See [instructions/…]` lines leave the instruction files out of Claude's context too. Switching them to `@instructions/…` imports loads them in every session, at an estimated 7-9k tokens, and the Codex render then has to expand the imports as it inlines links today.
- [ ] A Codex write can still slip between the render's last check and its rename of `codex/config.toml` (a window of microseconds; Codex takes no lock), and the reverse holds too: a Codex rename that lands after a render dropped a key brings the key back, and later renders then keep it as Codex's own. Keeping dropped paths in the state until a render sees them gone would close the second.
- [ ] `claude/settings.json` and `MEMORY.md` have the same read-merge-replace window as Codex's config had; reuse `_read_live` / `_replace_unless_changed` for them.
- [ ] `install.py` compares `~/.claude.json` keys against `global-config.base.json` with `!=`, so `0` passes for `false`; use `same_data`.
- [x] Memories agents write no longer go unnoticed. `overlay.py status` lists every file in the view directories that no repo tracks as `UNFILED`, and `overlay.py file <path> --to base|<alias> [--host <host>]` moves it and its index line to the owner.

## Publishing & CI

- [x] **PyPI account + tokens** — `tot0rokr` account on both pypi.org and
      test.pypi.org, with 2FA and an `agents-publish` API token. `.pypirc`
      configured locally for both repositories.
- [x] **`v0.3.1` published** — wheel + sdist on
      https://pypi.org/project/integrated-harness-kit-mcp/0.3.1/ and on
      TestPyPI. `uvx integrated-harness-kit-mcp` resolves end-to-end.
- [ ] **Publish the current version** (`mcp/pyproject.toml` says 1.2.0; PyPI still serves 0.3.1) so `uvx integrated-harness-kit-mcp` works again and machines stop running a package that predates overlays and `base/`. Blocked on nothing but the release chore now that the container E2E passes. Until then `INSTALLATION.md` Step 5 installs from the clone, which the document says plainly.
- [x] **`mcp>=1.0` was an unbounded dependency and PyPI now serves 2.x**, where `FastMCP` was renamed to `MCPServer`. Every published version to date fails to start on a machine that resolves the dependency today — found by the container test, not by the unit tests, which never import `mcp`. `server.py` now imports whichever name exists, and the protocol E2E runs against both majors.
- [x] **Docker fresh-env E2E test** — `test/e2e_v1.py` runs the whole story in the container built from `test/Dockerfile`: bootstrap on an empty `$HOME`, add a private overlay, settings and MCP writes, all three render scopes, routing, scaffolding, setup steps, drift and commits, then a scan of every tracked file for the overlay's freshly generated secret and hostname. 56 assertions. `test/e2e_mcp_protocol.py` additionally drives the installed server over stdio — 16 assertions, run against `mcp<2` and `mcp>=2`.
- [x] **`INSTALLATION.md` walkthrough, automated** — `test/walkthrough_install.sh` runs every command the document tells the agent to run, in a clean container, and checks each one: clone, install, doctor, the MCP entry and its verification command, then the overlay step. 19 assertions. The doc drifting from what works now fails a test.
- Dropped on 2026-11-23 by the maintainer's choice: CI (GitHub Actions for the unit tests and the container scripts), a CHANGELOG, and replaying `INSTALLATION.md` with a real agent. The tests run by hand in Docker.

## Housekeeping

- [x] `shared/memory/user_git_identity.md` + the matching line in
      `shared/memory/MEMORY.md` — moved into the work overlay with its
      index line, so the work email never reaches this public repo.
- [x] The install's rollback copies of the old `~/.claude` and `~/.config/opencode` — removed after months of stable use.
- [x] `~/.pypirc` keeps the original, now-revoked PyPI token in its `[pypi]` section, by the maintainer's choice; the working `agents-publish` token is supplied via env var per session. A `twine upload` without that variable would read the dead token and be refused.
- [x] `doctor.sh` checks that every `universal/skills/*/SKILL.md` names its own directory (FAIL), warns about a skill directory with no SKILL.md, and skips `synced/` (Claude Code's cache of claude.ai skills) and `.trash/`.
- [x] `doctor.sh` re-runs `render-mcp.sh` and `render-gemini-commands.sh` on copies under a temporary HOME and fails when the tracked `opencode/opencode.json`, `gemini/settings.json` or `gemini/commands/` differs. It found `gemini/commands/` stale on its first run: `account-switcher.toml` had never been rendered and `commit.toml` predated the 2026-11-20 `commit.md`.
- [ ] `render-gemini-commands.sh` renders every file in `shared/commands/`, so a command an overlay supplies there would land in the public `gemini/commands/`. Render from the base's tracked commands only, as `render-mcp.sh` renders the per-tool configs from `base/mcp/servers.json`; doctor's comparison already does.
- [ ] Consider porting `doctor.sh` to a Python module under
      `scripts/doctor.py` so the MCP's `doctor` tool can call it
      in-process instead of via subprocess.
