# Overlays

This repo is public. Anything environment-specific — employer hostnames, project names, IPs, ports, account IDs, credentials, personal paths — must never land in its history. Overlays are the mechanism that keeps that separation structural instead of relying on care at commit time.

An overlay is a separate git repo holding one environment's slice of the harness. The base repo stays generic; overlays carry the specifics. A personal overlay is private, a work overlay is private and can live on an internal host, and `templates/overlay-example/` is the public skeleton anyone can copy.

## Layout

An overlay mirrors the base repo's content namespaces:

```
overlay.json          # manifest: name, priority, description
memory/*.md           → shared/memory/
memory/MEMORY.md      → appended to shared/memory/MEMORY.md (index lines for the memories above)
memory/hosts/<host>.md → appended right after it, only on the machine whose short host name is <host>
                        (AGENTS_HOST overrides the name); for memories that hold on one machine only
instructions/*.md     → shared/instructions/
commands/*.md         → shared/commands/
subagents/*.md        → shared/subagents/
skills/<name>/        → universal/skills/
settings/claude.json  → merged into claude/settings.json
settings/claude.local.json → merged right after it, on this machine only (*.local.json stays out of the overlay's git)
settings/codex.toml   → merged into codex/config.toml
settings/codex.local.toml → merged right after it, on this machine only (*.local.toml stays out of the overlay's git)
mcp/servers.json      → merged into shared/mcp/servers.json
mcp/servers.local.json → merged right after it, on this machine only
vars.json             # ${VAR} values for JSON fragments (never commit to a public overlay)
vars.local.json       # this machine's ${VAR} overrides (gitignored like every *.local.json)
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

Higher `priority` wins when two overlays want the same thing — a JSON key or a file path. Ties break on alias, alphabetically. The order overlays happen to be installed in does not matter: a later install of a lower-priority overlay defers, and a later install of a higher-priority one takes the path over, reporting both as `DEFER` and `TAKE`. Remove the winner and the path falls back to the overlay that had deferred.

A file the base repo itself provides is the one exception: an overlay may not shadow it, and `install` refuses rather than hiding a tracked file behind a symlink.

## The base is layer 0

The base repo is a layer too, with priority 0, under every overlay (`scripts/layers.py`). It has the parts an overlay has. The view files stay where the tools read them, so applying the base links nothing; the files only a render reads sit under `base/`, with the names an overlay gives them under `overlays/<alias>/`:

```
overlay part           where the base keeps it
overlay.json           base/overlay.json
memory/MEMORY.md       base/memory/MEMORY.md
settings/claude.json   base/settings/claude.json
settings/codex.toml    base/settings/codex.toml
mcp/servers.json       base/mcp/servers.json
memory/ instructions/  shared/memory/, shared/instructions/
commands/ subagents/   shared/commands/, shared/subagents/
skills/<name>/         universal/skills/<name>/
```

`overlay.py list` shows it as the first row, and `setup` and `status` run its `base/overlay.json` setup steps before any overlay's (`overlay.py setup base --only <id>`). The alias `base` is reserved, so no overlay can be registered under it. A base step is a `run` or `manual` step only: the agent guardrail forbids touching the base repo's tracked files.

An overlay's files reach the base tree in one of two modes: `symlink` (described next, the default) or `checkout` (see "Checkout mode" below). An `"apply"` key in `overlay.json` names the mode; without one, the clone's layout decides. Any other value makes `install` refuse the overlay. `overlay.py list` shows each overlay's mode.

## How an overlay is applied

In symlink mode, Markdown and skill drop-ins are symlinked from the overlay clone into the base tree (checkout mode, below, keeps them as real files instead). Nothing is copied, so `git -C overlays/<alias> pull` is enough to pick up changes, and provenance stays obvious when you look at the file. The symlinks are registered in `.git/info/exclude` so they never appear as untracked files in the base repo.

JSON fragments are merged, because two sources have to coexist in one file that the tool actually reads.

## Checkout mode

Symlinked files have one weakness: `grep -r`, `rg` and `fd` do not follow symlinks by default, so a search over `shared/memory` skips every overlay memory. In checkout mode an overlay's view files (memory, instructions, commands, subagents, skills) are real files in the view directories, tracked in place by the overlay's own git, so they are found like base files and there is still exactly one copy.

How it works:

- The clone stays at `overlays/<alias>/`, but its `core.worktree` is the harness root (`../../..`, relative to its `.git`), and `status.showUntrackedFiles` is `no`. Paths in the overlay repo are relative to the harness root: `shared/memory/x.md`, `universal/skills/<name>/...`, and everything else under `overlays/<alias>/` (manifest, settings, MCP, `memory/MEMORY.md`, tools). The manifest's `links` stay symlinks.
- In the base, each view file is listed in the `.git/info/exclude` block, so `git status` stays clean and `git add` refuses it as ignored. rg and fd honour that exclude too, so `overlay.py` keeps a marked block of `!` lines in `.ignore` (read by rg and fd, never by git; itself excluded) that makes the files searchable again.
- `install` refuses a view path the base tracks, one another overlay already provides, or one with a symlink in the way. A symlink-mode overlay cannot take over a checkout overlay's file by priority: there is no link to swap.
- `install` puts three hooks in the clone. `pre-commit` refuses a commit that takes in a path outside `overlays/<alias>/` and the view directories, or one the base tracks. `post-commit` and `post-merge` run `overlay.py sync-views`, which refreshes the exclude block and `.ignore` so a newly committed view file never shows as untracked in the base.

Working with git in a checkout overlay:

- Run git from `overlays/<alias>` (or `git -C overlays/<alias>`). `git status` lists only tracked changes, and porcelain paths are relative to the harness root.
- Files under `overlays/<alias>/` sit inside the base's ignored `overlays/`, and the overlay shares that `.gitignore`, so `git add <path>` refuses them even when they are tracked. Stage an edit with `git add -u <path>` (or `git commit -- <path>`), and a new file with `git add -f <path>`. View files (`../../shared/memory/x.md`) are added normally.
- Never `git add -A` there: from the overlay's side every base file is untracked. The guard refuses the commit, but the index is then polluted until `git reset`. The MCP `overlay_commit` tool stages only tracked changes unless given paths.

Commands:

- `add` clones with `--no-checkout`; a repo whose manifest is at `overlays/<alias>/overlay.json` is checked out in place, after refusing any view path the base tracks or that already exists. `checkout-index` only writes missing files.
- `update` pulls a checkout overlay normally. For a symlink-mode clone whose upstream has moved to the checkout layout, it stops and says to run `convert`: pulling that layout into a symlink clone would move every file under `overlays/<alias>/overlays/<alias>/`.
- `convert <alias> [--source <remote or path>] [--dry-run]` switches a symlink-mode clone in place. The target commit must be a pure restructure (every path moved to `overlays/<alias>/<same>` or to its view path, no content changed); `convert` fast-forwards to the commit before it if needed, saves `.git/config`, `.git/index` and the old HEAD under `.git/agents-convert-<time>/`, switches git's index without touching a file, renames each view file over its symlink, fills in any missing view file from git, and re-applies. A local edit or deletion survives; nothing the base has is written.
- `remove` of a checkout overlay deletes its view files, so it needs `--purge` and a clean clone with nothing unpushed.

Moving an overlay to checkout mode: make the restructure commit in a scratch clone (`git mv` only), then `overlay.py convert <alias> --source <scratch clone>` on this machine, after a backup. Push the harness repo before the overlay. Another machine then pulls the harness first and runs `overlay.py update`, which stops at the new layout, and then `overlay.py convert <alias>`; a machine still on an older harness would pull the restructure as a plain fast-forward and lose the overlay until it is converted.

## Filing new content

A new file in a view directory belongs to nobody until someone decides: the base (public) or an overlay (private). `shared/AGENTS.md`, "Where new content goes", says how to decide. Three things keep that decision from being skipped:

- `overlay.py status` lists every file or skill directory in the view directories that no repo tracks as `UNFILED`. The rendered memory index, `MEMORY.md`, never counts.
- `overlay.py file <path> --to base|<alias>` stages it in the chosen repo. For a checkout overlay it stays in place and joins the exclude block and `.ignore`; for a symlink overlay it moves under `overlays/<alias>/` and is linked back. A memory's index line moves from the rendered index to the owner's index source (`base/memory/MEMORY.md`, or `overlays/<alias>/memory/MEMORY.md`; with `--host <host>`, the overlay's `memory/hosts/<host>.md`, so only that machine indexes it). Nothing is committed: review and commit in that repo.
- `overlay.py install` puts a pre-commit hook in the base repo (`overlay.py check-staged`) that refuses a commit taking in a path an overlay provides, or anything inside a registered overlay's clone. A hook someone else wrote is never overwritten; install warns instead.

To undo a conversion: restore `.git/config` and `.git/index` from the saved directory, `git reset --soft` to the saved HEAD, move the view files back under `overlays/<alias>/`, and run `overlay.py install <alias>` to recreate the symlinks.

`${VAR}` placeholders are substituted in JSON fragments, in TOML fragments (in keys too, so `[projects."${CLAUDE_HOME}/work"]` works) and in the overlay's `memory/MEMORY.md` index fragment. Values come from three layers, later ones winning: a built-in `CLAUDE_HOME` set to this machine's home directory, the overlay's `vars.json`, then this machine's `vars.local.json`. Leave anything that differs per machine — a home path, a port — out of `vars.json`, or one machine's value ends up on every other. Markdown drop-ins are used verbatim (symlinked, or checked out in place) — an overlay that needs private text in a memory file simply keeps that text in its own (private) repo, so there is nothing to substitute.

## Rendered artifacts, not tracked ones

Claude Code reads exactly one user-level settings file, `~/.claude/settings.json`, and writes to it at runtime (`autoMode.environment`, for one, is generated and contains a description of your environment). With `~/.claude` symlinked into this repo, that runtime write lands directly in a tracked file — which is how employer hostnames ended up staged for a public repo once already.

So the file is split:

- `base/settings/claude.json` — tracked, public-safe, hand-edited
- `claude/settings.json` — build artifact, gitignored
- `scripts/render_settings.py` — produces the artifact

Render order is base, then each enabled overlay by ascending priority, then a final pass that carries over every key the live file has but no source manages, and every hook no source has (see [What an overlay can and cannot overwrite](#what-an-overlay-can-and-cannot-overwrite)). That last pass is what keeps runtime-written state working while leaving it untracked forever.

`LOCAL_ONLY_KEYS` in `render_settings.py` lists keys that must never appear in the tracked base. `render_settings.py --check` fails if one does, and `doctor.sh` runs that check.

A key like `autoMode` describes one machine, so an overlay that serves several machines should not carry it in its shared `settings/claude.json` either. Put it in `settings/claude.local.json` beside it: the renderer merges that file right after the overlay's own fragment, and the overlay's `.gitignore` keeps `*.local.json` on the machine that wrote it. `mcp/servers.local.json` works the same way.

A local fragment overrides its own overlay's shared fragment and nothing more: a higher-priority overlay's shared fragment is merged later and still wins. Overlays scaffolded by `init` get the `.gitignore` rules from the template; an older overlay needs `*.local.json` and `*.local.toml` added by hand. Until then `overlay.py install` warns and `overlay.py status` reports a `LOCAL` problem for any local fragment git would still pick up, and the MCP tool `overlay_commit` refuses to commit a `*.local.json` or `*.local.toml` file, unstaging it, whatever the `.gitignore` says. Because the file lives nowhere else, `remove --purge` deletes this machine's only copy.

Those files hold this machine's credentials, and git and editors write them at the umask's mode, so `overlay.py` keeps `overlays/` itself at mode 700 (it closes an existing one on `add`, `install`, `update` and `remove`), and `doctor.sh` warns while it is not.

The MCP tools `settings_set`, `mcp_server_set` and `mcp_server_remove` write these files with the target `overlay:<alias>:local`, and `settings_get` reports keys from them as `overlay:<alias>:local`.

Editing `claude/settings.json` by hand still works — the edit survives as unmanaged state — but it will not be tracked. Anything you want tracked belongs in `base/settings/claude.json`; anything environment-specific belongs in an overlay.

The memory index gets the same split. `base/memory/MEMORY.md` is tracked; `shared/memory/MEMORY.md` is rendered from it, then each enabled overlay's `memory/MEMORY.md` by ascending priority, then every line the live file has that no source claims. Agents append index lines to the live file at runtime, and that last pass is what keeps them.

A memory an agent writes therefore lands in `shared/memory/` as an untracked file, with its index line carried only in the rendered `MEMORY.md`. It stays on this machine until someone files it: into the base (the file plus a line in `base/memory/MEMORY.md`) when it is safe to publish, or into an overlay (the file plus a line in that overlay's `memory/MEMORY.md`) when it is not. A memory that only matters inside one project can go to that project's own `~/.claude/projects/<slug>/memory/` instead, provided that slug is not linked to `shared/memory`; only Claude Code sessions started in that directory see it, and no repo tracks it.

### Codex

Codex has the same problem in TOML: it writes into `~/.codex/config.toml` whenever you trust a directory, pick a model or dismiss a notice, and a trusted directory is an absolute path on one machine. So that file is split too:

- `base/settings/codex.toml` — tracked, public-safe, hand-edited
- `codex/config.toml` — build artifact, gitignored, mode 600
- `scripts/render_settings.py` — produces it in the same pass as the others

Render order is the base, then the MCP servers from the rendered `servers.json`, then each enabled overlay's `settings/codex.toml` and `settings/codex.local.toml` by ascending priority, then every key the live file has that no source claims. That last pass keeps what Codex wrote for itself: trusted projects, UI counters, keys a newer Codex adds. Keys a past render managed and no source holds any more are dropped, tracked under `codexManaged` in `overlays/rendered.local.json`.

A table no source holds any more loses only what a render put there: remove the overlay whose `[projects.*]` started the `projects` table and the directories Codex was told to trust stay. The tables in `CODEX_ATOMIC` go whole — an MCP server, a model provider, `otel` — because what Codex writes into one (an `enabled` flag, tool approvals) is no server on its own, and Codex refuses the whole file over a server without `command` or `url`, or an exporter without its `endpoint`.

On an MCP server a source defines, the live keys of the other transport are dropped too, with a warning: `codex mcp add linear -- npx ...` over a server the sources define by `url`, or a pre-harness config that `install.py` seeds, would otherwise leave `command` next to `url`, and Codex rejects the whole file over that one table. The same goes the other way for `url`, the header and bearer-token keys and the `oauth` table `codex mcp add --oauth-client-id` writes. Keys that work on either transport, timeouts and tool filters among them, are kept.

Until 2026-10 the file was tracked, so on a machine where Codex had not touched it the pull that untracked it deleted it. While `codexManaged` is not recorded yet, a missing live file is read back from the newest commit in HEAD's reflog (or `ORIG_HEAD`) that still had it, which is the copy that pull removed.

Every key in the base is enforced, `model` and `service_tier` included: switch either inside Codex and the next render puts the base value back, with `overlay.py status` reporting DRIFT until then. `CODEX_LOCAL_ONLY` lists what may never be in the base — `projects` (machine paths; trusted projects belong in an overlay's `settings/codex.toml`), `mcp_servers` (they come from `shared/mcp/`) and `tui.model_availability_nux` — and `render_settings.py --check` fails on any of them.

Because the file now carries overlay MCP servers, credentials included, it is written with mode 600. So is `shared/mcp/servers.json`, rendered in the same pass from the same sources: a credential is only as private as the most readable file that holds it. A render that finds either file current but looser tightens it without rewriting it. The renderer refuses to write `codex/config.toml` while git still tracks it. The comparison that decides whether to write is on parsed data, not text: Codex rewrites the file in its own formatting, and that is not drift. A value of another type is, though: `1` where the source says `true`, or `65536.0` where it says `65536`, makes Codex refuse the whole file, so the render rewrites it. (In `settings.json` a number in place of a boolean is drift too, but `1` and `1.0` are the same JSON number.) Comments typed into the live file are lost on the next render that changes something; put them in the base.

Reading TOML takes `tomllib` (Python 3.11+) or `tomli`; with neither, this render alone is skipped with a warning and the live file is left untouched, since rendering it unread would drop what Codex wrote.

The live file has to stay TOML 1.0. Codex also reads TOML 1.1, so an inline table typed over several lines or ending in a comma works in Codex, but Python's `tomllib` cannot read it, and the render stops on a live file it cannot read rather than render over what Codex wrote there. Rewrite such a table as a `[table]` and render again.

A source that does not parse stops the render before anything is written. Every artifact is computed first, so a typo in an overlay's `settings/codex.toml`, say, fails the whole render with an error naming that file and leaves all five artifacts as they were, instead of updating Claude's settings and leaving Codex's config behind. That holds for `overlay.py remove` too: the overlay is unregistered, but its servers and settings stay in the rendered files until a render succeeds. A failure while writing is different — a full disk, or Codex rewriting its config on every attempt — and can leave the artifacts written before it updated; the next render that succeeds brings the rest in line.

A running Codex can write the file while a render merges it. The renderer replaces the file only if it is still the one it read (same inode, size and mtime); otherwise it merges again from what Codex wrote, and after five changed attempts it stops with an error and leaves the file to Codex.

Codex also does not follow links, so the instruction files `shared/AGENTS.md` links to never reached it. The same pass renders `codex/AGENTS.override.md`, which Codex reads in place of `AGENTS.md`: every `See [instructions/<x>.md](...)` line is replaced by that file's body, one heading level down, and the remaining relative links become absolute paths. A line that says more after the link is kept above the body; code blocks and code spans are copied untouched. An overlay's `instructions/personal.md` is inlined like any other; a link to a file that is absent is dropped. A line that is only a Claude Code import, `@memory/MEMORY.md`, is replaced the same way by the file's body, so Codex gets the shared memory index that Claude Code loads through the import; the index used is the one the same pass renders. Codex reads this global file whole (checked with codex-cli 0.163 up to 300 KB); its 32 KiB `project_doc_max_bytes` cap applies only to the `AGENTS.md` and `AGENTS.override.md` files it finds in a project, so `doctor.sh` reports the size without a limit.

## Commands

```
scripts/overlay.py add <alias> [<git-url>] [--ref REF] [--priority N]
scripts/overlay.py install [<alias>] [--dry-run]
scripts/overlay.py list
scripts/overlay.py status
scripts/overlay.py setup [<alias>] [--dry-run] [--yes] [--only ID...] [--interactive]
scripts/overlay.py update [<alias>]
scripts/overlay.py remove <alias> [--purge]
scripts/overlay.py init <dir> [--name NAME]
```

`add` registers an overlay, cloning it into `overlays/<alias>` when nothing is there yet. When the clone is already in place — the machine the overlay was authored on, or one where you cloned it by hand — leave the URL off and it registers what it finds, taking the URL and ref from the clone itself. Without `--priority`, the priority comes from the overlay's `overlay.json` (50 if it declares none); it is read once, at `add`, so a later change to the manifest needs `remove` and `add` again to take effect. `install` applies every enabled overlay, or just the one named. With `--dry-run` it changes nothing and reports what a real run would: each link it would add (`LINK`) or remove (`UNLINK`), the `.git/info/exclude` lines that would change (`EXCLUDE`), and for every rendered file the keys (JSON, TOML) or lines (Markdown) the render would add, change or remove (`RENDER`). Values under `env` and header tables, and under keys naming a token, secret, password or auth, print as `<hidden>`. The render preview reads `shared/instructions/` as it is linked at that moment; when the run would change those links it says so. `update` pulls and re-applies. `remove` unlinks what the overlay contributed and re-renders; `--purge` also deletes the clone. `init` scaffolds from `templates/overlay-example/`, into `overlays/<alias>` for a bare alias or wherever a path points.

## Routing records to the right overlay

Session summaries, journal entries and anything else written *about* a piece of work belong to whichever environment that work is part of — and the harness can decide that instead of a person deciding it every time. An overlay declares what it owns:

```json
{
  "claims": {
    "remotes": ["*.corp.example"],
    "paths": ["~/work", "~/client-project"],
    "default": false
  }
}
```

`remotes` matches the `origin` host of the git repo containing the path; `paths` matches the path itself, by glob or by prefix. `overlay.py route <path>` answers with the winning alias — highest priority among the overlays that claim it, or the one marked `default` when nothing claims it.

```bash
scripts/overlay.py route ~/client-project           # work
scripts/overlay.py route ~/agents                   # personal
scripts/overlay.py route --explain                  # …and why, for the current directory
scripts/overlay.py route --dir session-logs --mkdir # the directory to write into
```

The routing is realised with links, so a tool that just writes to a fixed path still lands in the right repo. Each overlay owns a subdirectory of the records directory:

```
claude/session-logs/work     -> overlays/work/session-logs
claude/session-logs/personal -> overlays/personal/session-logs
```

The parent stays a plain gitignored directory in the base, so anything written without routing sits there, local and untracked, until someone files it.

What does *not* go into an overlay is the raw transcript. `~/.claude/projects` is hundreds of megabytes, grows with every conversation, and records every file read and command output verbatim — git would keep all of it forever, including whatever secret happened to be on screen. Summaries are the thing worth versioning.

## Setup steps

Some of an environment cannot be expressed as files: a credential file the MCP server reads, a systemd unit, a `gh` login, a password that belongs in the environment rather than in any repo. An overlay declares those as `setup` steps in its manifest, and `overlay.py setup` works through them. The base declares its own in `base/overlay.json` (for one, the `termaid` CLI), and they come first.

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

Step commands and prompts see the same variables (built-in `CLAUDE_HOME`, `vars.json`, `vars.local.json`) as environment variables, and `${VAR}` in a prompt file is substituted before the agent sees it.

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
- `rendered.local.json` — the key paths (`managed`, `codexManaged`) and index lines (`memoryLines`) the last render wrote, so a key dropped from every source is dropped from the artifact instead of living on as runtime state.

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

`shared/mcp/servers.json` is rendered the same way, from `base/mcp/servers.json` plus each overlay's `mcp/servers.json`. An internal MCP server — one whose URL or command names an employer host — belongs in a private overlay, never in the base.

Nothing writes `servers.json` at runtime, so it needs no unmanaged-key preservation: removing an overlay removes its servers cleanly. It carries the overlays' servers with their `headers` and `env`, and a value an overlay substitutes from `vars.local.json`, or sets in `servers.local.json`, lands in it verbatim, so it is written with mode 600 like `codex/config.toml`.

`render-mcp.sh` reads two sources. Only `~/.claude.json`, which lives outside the repo, gets the rendered set with overlay servers; the tracked per-tool configs (`opencode/opencode.json`, `gemini/settings.json`) are rendered from `base/mcp/servers.json` alone, and `doctor.sh` fails if an overlay-only server shows up in one of them. Codex is not in that list: `codex/config.toml` is an untracked artifact, so `render_settings.py` writes the overlay-merged set into it, leaving out any server Codex cannot run (SSE, or one with neither `url` nor `command`), because one bad server table makes Codex reject the whole file. Into `~/.claude.json` it merges per server, so a value that exists only on this machine — a password left out of every repo — and a server registered there by hand both survive the render.

Tokens and passwords do not belong in an overlay either. Reference them from the environment in the server definition, keep the values in your secret store, and export them where the tools start their MCP servers. Three shapes work for both tools:

```json
"env":     { "API_TOKEN": "${API_TOKEN}" }
"headers": { "Authorization": "Bearer ${API_TOKEN}", "X-Api-Key": "${API_KEY}" }
```

Claude Code expands `${VAR}` itself when it starts a server. Codex does not: it would send the text `${API_TOKEN}`. So the render turns these shapes into the fields Codex fills from its own environment, `env_vars`, `bearer_token_env_var` and `env_http_headers`. Codex reads them from the process that starts its MCP servers, which by default is its shared background app-server, not the `codex` you just ran: a variable exported after that app-server started does not reach it, while `codex --no-daemon` uses the shell's own environment. Any other `${...}` reaches a Codex server as written, and the render warns about it. That covers a renamed variable (`"GITHUB_TOKEN": "${GH_PAT}"`), a reference inside a longer value, `${VAR:-default}`, and one in `url`, `command` or `args`. When the variable is unset, Claude Code passes the unexpanded text on, Codex leaves the variable or header out, and it does not start a server whose bearer token is missing. Keep a secret's name out of `vars.json` and `vars.local.json`: a variable defined there is substituted at render time and written into the rendered files in plain text.

## What an overlay can and cannot overwrite

Applying an overlay never deletes a setting that no source claims — `test/qa_interference.py` walks thirteen before-and-after scenarios and none of them loses data. Three behaviours do surprise people, though, and they are deliberate:

A list is replaced, not appended to — unless the key says otherwise. If the base defines `hooks.Stop` and an overlay defines `hooks.Stop`, the overlay's list is what survives; sibling events like `hooks.PreCompact` are untouched. To add to a list rather than own it, write the key with a trailing `+`:

```json
{ "hooks": { "Stop+": [ { "type": "command", "command": "..." } ] } }
```

That appends to whatever `hooks.Stop` holds so far and leaves the key named `Stop`. Several sources may append to the same list; they land in source order, which is priority order. Objects always merge key by key, with or without the marker.

Hooks in the live file are merged, not replaced. Tools add hooks to `settings.json` themselves: claude-auto's `install.sh` appends its own to `PostToolUse` and `UserPromptSubmit`, events the base uses too, so replacing those lists dropped them on every render. Within each event the render writes the sources' hooks first, then every hook of the live file whose command no source has for that event, in the group it came in, matcher included. A hook a source has is written as the source has it, so the source's timeout or matcher wins. The exception is a hook that runs a script from the harness's own `claude/hooks/` (`$HOME/.claude/hooks/…`). Only a source registers those, so one no source has is left over from before a source renamed or dropped it, and the render drops it. Any other hook a source drops stays in the live file, since nothing tells it from one a tool added. Each render lists on stderr the hooks it kept that way and the ones it dropped; delete a stale one from `claude/settings.json` by hand.

The marker exists in JSON fragments only. In a TOML fragment (`settings/codex.toml`, `settings/codex.local.toml`) every key is taken as written, because Codex keys are paths and names: `[projects."${CLAUDE_HOME}/c++"]` trusts `c++`, not an append to `c+`. A list a TOML fragment sets replaces the one before it.

A key some source claims is restored from that source on the next render. Change `model` by hand in the rendered `settings.json` and the next render puts the base's value back — that is how a tracked setting stays tracked. Change it in `base/settings/claude.json` or in an overlay instead. Keys no source claims, which is most of what Claude Code writes at runtime, are carried across untouched. That holds inside an object too: remove the only overlay that sets `enabledPlugins` and its plugins go, while the ones Claude Code installed stay. `statusLine` and the other objects listed in `CLAUDE_ATOMIC` are the exception and go whole, since Claude Code skips the entire settings file over one that lacks its `type` or `command`.

Editing a rendered artifact is always temporary. `claude/settings.json`, `shared/mcp/servers.json`, `shared/memory/MEMORY.md`, `codex/config.toml` and `codex/AGENTS.override.md` are outputs; a server added straight into `servers.json` disappears on the next render. Edit the `.base.` file or the overlay fragment.

One rough edge worth knowing: if you edit a *base* line of `shared/memory/MEMORY.md` in place, the render keeps your edited line — it looks like a line no source claims — and restores the original alongside it, so the index ends up with both. Edit `base/memory/MEMORY.md` or the overlay's fragment instead.

## Known gaps

Gemini and OpenCode configs are still tracked and rendered from the base alone, so they get no overlay MCP servers. They would need the same split Codex got.

`.git/info/exclude` is shared by every worktree of the repo, so applying an overlay inside a worktree also hides those paths in the main checkout. Harmless when the names do not collide, but worth knowing when testing an overlay from a worktree.
