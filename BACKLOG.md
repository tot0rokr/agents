# Backlog

Outstanding work for the unified agents harness and its companion MCP package. Items are roughly priority-ordered within each section. Tick when done so the file stays trustworthy.

## Content to fill in

- [x] `universal/skills/` — 4 registered (`bash-command-style`,
      `critical-file-safety`, `git-commit-workflow`,
      `safe-file-operations`). Discoverable via `~/.claude/skills` and
      `~/.agents/skills`.
- [x] `shared/mcp/servers.json` — Linear MCP (remote HTTP, OAuth 2.1).
      `render-mcp.sh` handles remote vs stdio per tool.
- [x] `shared/subagents/` — 3 sub-agents (Claude + OpenCode shared):
      `code-reviewer`, `agents-harness-auditor`, `linear-triage`.
      Codex/Gemini variants would need separate render scripts; deferred.
- [x] `shared/commands/` — `/commit`, `/review`, `/audit`. Claude/Codex/
      OpenCode read `.md` directly; Gemini gets `.toml` via
      `render-gemini-commands.sh`.
- [ ] `shared/output-styles/` — Claude-only feature today. Add when needed.

## Live verification

- [x] `scripts/render-mcp.sh` — 4 tools render correctly; idempotent on
      re-run; preserves Codex CLI-written sections like
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
- [ ] **v0.5.0** — maintenance tools: `update` (git pull + render +
      doctor), `audit_drift` (uncommitted change classification),
      `commit` (staged commit following `git-commit-workflow` skill),
      `edit_memory` / `edit_instruction` (write `shared/memory/<name>.md`
      or `shared/instructions/<topic>.md`).

## Publishing & CI

- [x] **PyPI account + tokens** — `tot0rokr` account on both pypi.org and
      test.pypi.org, with 2FA and an `agents-publish` API token. `.pypirc`
      configured locally for both repositories.
- [x] **`v0.3.1` published** — wheel + sdist on
      https://pypi.org/project/integrated-harness-kit-mcp/0.3.1/ and on
      TestPyPI. `uvx integrated-harness-kit-mcp` resolves end-to-end.
- [ ] **`v0.4.0` publish** — wheel + sdist built and `twine check`ed.
      TestPyPI and PyPI upload still pending (see `mcp/dist/`). Needs
      Docker E2E verification (below) before going public.
- [ ] **Docker fresh-env E2E test** — `test/Dockerfile` runs a clean
      Ubuntu + python3 + git + uv container so the maintainer can `exec`
      in and replay `INSTALLATION.md` step-by-step. Verifies the bootstrap
      story against a machine that has *never* seen this repo.
- [ ] **`INSTALLATION.md` live walkthrough** — once Docker E2E is wired,
      run the doc end-to-end exactly as a fresh user would: paste the
      file to a CLI agent inside the container, prompt
      "이대로 설치해줘", confirm the agent reaches doctor: PASS without
      manual intervention.
- [ ] **GitHub Actions CI** that runs `python3 scripts/test_install.py`
      and `python3 -m unittest discover -s mcp/tests` on PR. Optional
      matrix over Python 3.10/3.11/3.12. Once green, extend with a
      `pypi-publish` workflow that builds + uploads on tag push (uses
      repository secret `PYPI_API_TOKEN`) so we stop hand-rolling
      `twine upload`.
- [ ] **CHANGELOG.md** — bump versions there alongside tags. Currently
      the release narrative lives only in commit messages.

## Housekeeping

- [ ] `shared/memory/user_git_identity.md` + the matching line in
      `shared/memory/MEMORY.md` — still uncommitted. Holds the user's
      work email; this is a public repo. Decide: mask the email and
      commit, or keep working-tree only forever.
- [ ] `~/.claude.bak.20260512-183533` and
      `~/.config/opencode.bak.20260512-183533` — remove after ~1 week
      of stable use (currently retained as rollback insurance).
- [ ] `~/.pypirc` has the original, now-revoked PyPI token in its
      `[pypi]` section; the working `agents-publish` token is supplied
      via env var per session. Replace the `[pypi]` password with the
      live token (chmod 600 verified). Cleared by the maintainer's
      explicit choice for now ("key는 그대로 둘래").
- [ ] `doctor.sh` improvement: validate every
      `universal/skills/*/SKILL.md` has a `name:` matching its directory
      name. Catches the most common Claude-discovery mistake.
- [ ] `doctor.sh` improvement: run each `render-*.sh` against `mktemp`
      copies and diff against the in-tree file. Flags render drift
      before it lands in a commit.
- [ ] Consider porting `doctor.sh` to a Python module under
      `scripts/doctor.py` so the MCP's `doctor` tool can call it
      in-process instead of via subprocess.
