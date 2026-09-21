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
scripts/overlay.py add <alias> <git-url> [--ref REF] [--priority N]
scripts/overlay.py install [<alias> | --all]
scripts/overlay.py list
scripts/overlay.py status
scripts/overlay.py update [<alias>]
scripts/overlay.py remove <alias> [--purge]
scripts/overlay.py init <dir> [--name NAME]
```

`add` registers and clones. `install` applies. `update` pulls and re-applies. `remove` unlinks what the overlay contributed and re-renders; `--purge` also deletes the clone. `init` scaffolds a new overlay from `templates/overlay-example/`.

## State files

Both live under `overlays/`, which is gitignored in full:

- `registry.local.json` — alias, git URL, ref, priority, enabled. Holds internal URLs, so it stays local.
- `applied.local.json` — every link and merge an install produced. `remove` and `status` read it, so it is the record that makes removal exact rather than best-effort.

## Setting one up

```bash
scripts/overlay.py init ~/agents-overlay-personal --name personal
cd ~/agents-overlay-personal && git init && git add -A && git commit -m "initial overlay"
# push to a private remote, then:
cd ~/agents
scripts/overlay.py add personal <git-url>
scripts/overlay.py install personal
```

For a work environment, host the overlay on the employer's git server and register it the same way. Internal details never reach github.com.

## MCP servers

`shared/mcp/servers.json` is rendered the same way, from `shared/mcp/servers.base.json` plus each overlay's `mcp/servers.json`. An internal MCP server — one whose URL or command names an employer host — belongs in a private overlay, never in the base.

Nothing writes `servers.json` at runtime, so it needs no unmanaged-key preservation: removing an overlay removes its servers cleanly. `render-mcp.sh` reads the rendered file and is unchanged, so the per-tool configs pick up overlay servers on the next render.

Tokens and passwords do not belong in an overlay either. Reference them from the environment in the server definition and keep the values in your secret store.
