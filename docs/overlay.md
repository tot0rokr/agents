# Overlays

This repo is public. Anything environment-specific — employer hostnames, project names, IPs, ports, account IDs, credentials, personal paths — must never land in its history. Overlays are the mechanism that keeps that separation structural instead of relying on care at commit time.

An overlay is a separate git repo holding one environment's slice of the harness. The base repo stays generic; overlays carry the specifics. A personal overlay is private, a work overlay is private and can live on an internal host, and `templates/overlay-example/` is the public skeleton anyone can copy.

## Layout

An overlay mirrors the base repo's content namespaces:

```
overlay.json          # manifest: name, priority, description
memory/*.md           → shared/memory/
instructions/*.md     → shared/instructions/
commands/*.md         → shared/commands/
subagents/*.md        → shared/subagents/
skills/<name>/        → universal/skills/
settings/claude.json  → merged into claude/settings.json
mcp/servers.json      → merged into shared/mcp/servers.json
vars.json             # ${VAR} values for JSON fragments (never commit to a public overlay)
```

Anything outside those namespaces goes through the manifest's `links` map, which takes an overlay-relative path to a repo-relative one and symlinks it as-is. Files or directories both work:

```json
{
  "links": {
    "session-logs": "claude/session-logs",
    "output-styles/work.md": "shared/output-styles/work.md"
  }
}
```

Every directory is optional. An overlay that only carries two memory files is a valid overlay.

`overlay.json`:

```json
{
  "name": "work",
  "priority": 60,
  "description": "Employer environment: internal hosts, ticket conventions",
  "links": {}
}
```

Higher `priority` wins when two overlays set the same JSON key. Ties break on alias, alphabetically.

## How an overlay is applied

Markdown and skill drop-ins are symlinked from the overlay clone into the base tree. Nothing is copied, so `git -C overlays/<alias> pull` is enough to pick up changes, and provenance stays obvious when you look at the file. The symlinks are registered in `.git/info/exclude` so they never appear as untracked files in the base repo.

JSON fragments are merged, because two sources have to coexist in one file that the tool actually reads.

`${VAR}` placeholders are substituted in JSON fragments only, from the overlay's own `vars.json`. Markdown drop-ins are symlinked verbatim — an overlay that needs private text in a memory file simply keeps that text in its own (private) repo, so there is nothing to substitute.

## Rendered artifacts, not tracked ones

Claude Code reads exactly one user-level settings file, `~/.claude/settings.json`, and writes to it at runtime (`autoMode.environment`, for one, is generated and contains a description of your environment). With `~/.claude` symlinked into this repo, that runtime write lands directly in a tracked file — which is how employer hostnames ended up staged for a public repo once already.

So the file is split:

- `claude/settings.base.json` — tracked, public-safe, hand-edited
- `claude/settings.json` — build artifact, gitignored
- `scripts/render_settings.py` — produces the artifact

Render order is base, then each enabled overlay by ascending priority, then a final pass that carries over every key the live file has but no source manages. That last pass is what keeps runtime-written state working while leaving it untracked forever.

`LOCAL_ONLY_KEYS` in `render_settings.py` lists keys that must never appear in the tracked base. `render_settings.py --check` fails if one does, and `doctor.sh` runs that check.

Editing `claude/settings.json` by hand still works — the edit survives as unmanaged state — but it will not be tracked. Anything you want tracked belongs in `settings.base.json`; anything environment-specific belongs in an overlay.

## Commands

```
scripts/overlay.py add <alias> [<git-url>] [--ref REF] [--priority N]
scripts/overlay.py install [<alias> | --all]
scripts/overlay.py list
scripts/overlay.py status
scripts/overlay.py setup [<alias>] [--dry-run] [--yes] [--only ID...] [--interactive]
scripts/overlay.py update [<alias>]
scripts/overlay.py remove <alias> [--purge]
scripts/overlay.py init <dir> [--name NAME]
```

`add` registers an overlay, cloning it into `overlays/<alias>` when nothing is there yet. When the clone is already in place — the machine the overlay was authored on, or one where you cloned it by hand — leave the URL off and it registers what it finds, taking the URL and ref from the clone itself. `install` applies. `update` pulls and re-applies. `remove` unlinks what the overlay contributed and re-renders; `--purge` also deletes the clone. `init` scaffolds from `templates/overlay-example/`, into `overlays/<alias>` for a bare alias or wherever a path points.

## Routing records to the right overlay

Session summaries, journal entries and anything else written *about* a piece of work belong to whichever environment that work is part of — and the harness can decide that instead of a person deciding it every time. An overlay declares what it owns:

```json
{
  "claims": {
    "remotes": ["*.mangoboost.io"],
    "paths": ["~/bsp-work", "~/softhsm"],
    "default": false
  }
}
```

`remotes` matches the `origin` host of the git repo containing the path; `paths` matches the path itself, by glob or by prefix. `overlay.py route <path>` answers with the winning alias — highest priority among the overlays that claim it, or the one marked `default` when nothing claims it.

```bash
scripts/overlay.py route ~/softhsm                  # mangoboost
scripts/overlay.py route ~/agents                   # personal
scripts/overlay.py route --explain                  # …and why, for the current directory
scripts/overlay.py route --dir session-logs --mkdir # the directory to write into
```

The routing is realised with links, so a tool that just writes to a fixed path still lands in the right repo. Each overlay owns a subdirectory of the records directory:

```
claude/session-logs/mangoboost -> overlays/mangoboost/session-logs
claude/session-logs/personal   -> overlays/personal/session-logs
```

The parent stays a plain gitignored directory in the base, so anything written without routing sits there, local and untracked, until someone files it.

What does *not* go into an overlay is the raw transcript. `~/.claude/projects` is hundreds of megabytes, grows with every conversation, and records every file read and command output verbatim — git would keep all of it forever, including whatever secret happened to be on screen. Summaries are the thing worth versioning.

## Setup steps

Some of an environment cannot be expressed as files: a credential file the MCP server reads, a systemd unit, a `gh` login, a password that belongs in the environment rather than in any repo. An overlay declares those as `setup` steps in its manifest, and `overlay.py setup` works through them.

```json
{
  "setup": [
    {
      "id": "atlassian-env",
      "description": "Credential file the Atlassian MCP server reads",
      "check": "test -f \"$CLAUDE_HOME/.local/mcp/atlassian/mcp-atlassian.env\"",
      "agent": "setup/atlassian-env.md",
      "allowedTools": ["Bash", "Read", "Write", "Edit"],
      "manual": "Create an API token at <url>, then rerun"
    }
  ]
}
```

`check` is the gate and the only part that ever runs on its own: exit 0 means satisfied, anything else means pending. `install`, `update` and `status` evaluate checks and report, and never execute a step. Steps are idempotent by construction — a satisfied check is skipped.

A pending step is carried out by whichever of these it declares, in order: `run` (a shell command, for deterministic work), `agent` (a prompt file handed to Claude Code), or `manual` (text printed for the user, for anything a machine should not be doing on its own — collecting a secret, clicking through an SSO page). After `run` or `agent`, the check is re-evaluated, so the outcome is verified rather than assumed.

Step commands and prompts see the overlay's `vars.json` as environment variables, and `${VAR}` in a prompt file is substituted before the agent sees it.

### How the agent step runs

```
claude -p --output-format json \
  --permission-mode acceptEdits \
  --add-dir <overlay path> \
  --allowedTools Bash Read Edit Write Glob Grep \
  --append-system-prompt "<guardrail>" \
  "<prompt file, ${VAR} substituted>"
```

The guardrail tells the agent to do that one step and nothing else, never to touch tracked files in the base repo, never to commit or push, never to write a secret into a repo, and to answer BLOCKED with what it needs rather than inventing a credential. `--allowedTools` narrows that further per step; the default is the list above.

`--interactive` runs the same prompt in a live session instead of `-p`, which is what you want when the step needs a conversation — a token pasted in, a choice made, an error diagnosed. `--model` picks the model, `--permission-mode` is settable, and `bypassPermissions` is available but never the default.

### Safety

An overlay that can run commands is an overlay that can run *any* command, so nothing here happens implicitly. `overlay.py setup` prints the full plan first, and without `--yes` it refuses and exits non-zero; `--dry-run` shows the plan and stops. Read a new overlay's setup steps before you run them, the same way you would read an install script.

## State files

Both live under `overlays/`, which is gitignored in full:

- `registry.local.json` — alias, git URL, ref, priority, enabled. Holds internal URLs, so it stays local.
- `applied.local.json` — every link and merge an install produced. `remove` and `status` read it, so it is the record that makes removal exact rather than best-effort.

## Setting one up

```bash
scripts/overlay.py init personal                  # scaffolds overlays/personal
cd overlays/personal
git init -b main && git add -A && git commit -m "initial overlay"
git remote add origin <private-url> && git push -u origin main
cd ../..
scripts/overlay.py add personal                   # url comes from the clone
scripts/overlay.py install personal
```

The overlay lives inside the harness repo, at `overlays/<alias>`, and `overlays/` is gitignored in full — so a private overlay sits next to the base tree without ever being tracked by it. Edit and push it from there; the harness reads it in place.

On another machine the same overlay arrives by URL instead:

```bash
scripts/overlay.py add personal <private-url>
scripts/overlay.py install personal
```

For a work environment, host it on the employer's git server. Internal details never reach github.com. One consequence of nesting worth knowing: anything that copies `~/agents` wholesale — a backup, an rsync, a re-clone by directory copy — carries the private overlay with it.

## MCP servers

`shared/mcp/servers.json` is rendered the same way, from `shared/mcp/servers.base.json` plus each overlay's `mcp/servers.json`. An internal MCP server — one whose URL or command names an employer host — belongs in a private overlay, never in the base.

Nothing writes `servers.json` at runtime, so it needs no unmanaged-key preservation: removing an overlay removes its servers cleanly. `render-mcp.sh` reads the rendered file and is unchanged, so the per-tool configs pick up overlay servers on the next render.

Tokens and passwords do not belong in an overlay either. Reference them from the environment in the server definition and keep the values in your secret store.

## Known gaps

`render-mcp.sh` rewrites each tool's native config — for Claude Code, `~/.claude.json` — from the rendered `servers.json`. A server whose definition deliberately omits a secret (the BSP knowledge base leaves out `NEO4J_PASSWORD`) would have that value stripped from the live config on the next render. Until the renderer merges rather than replaces per-server `env` and `headers`, run it knowing that, and re-supply the secret afterwards.

Memory pointer lines have no overlay path. `shared/memory/MEMORY.md` is one tracked file in the public base, so the one-line index entry for an overlay-provided memory has nowhere private to live. It needs the same base/fragment split the JSON artifacts got, or an include mechanism.

`.git/info/exclude` is shared by every worktree of the repo, so applying an overlay inside a worktree also hides those paths in the main checkout. Harmless when the names do not collide, but worth knowing when testing an overlay from a worktree.
