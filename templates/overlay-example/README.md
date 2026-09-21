# Example overlay

A skeleton for one environment's slice of the [agents harness](https://github.com/tot0rokr/agents). Everything here is placeholder content — nothing in it is real.

Scaffold your own copy rather than editing this directory in place:

```bash
scripts/overlay.py init ~/agents-overlay-personal --name personal
```

Then `git init`, commit, push to a remote, and register it:

```bash
scripts/overlay.py add personal <git-url>
scripts/overlay.py install personal
```

## What goes where

| Path | Lands in | Applied as |
|---|---|---|
| `memory/*.md` | `shared/memory/` | symlink |
| `instructions/*.md` | `shared/instructions/` | symlink |
| `commands/*.md` | `shared/commands/` | symlink |
| `subagents/*.md` | `shared/subagents/` | symlink |
| `skills/<name>/` | `universal/skills/` | symlink |
| `settings/claude.json` | `claude/settings.json` | deep merge |
| `mcp/servers.json` | `shared/mcp/servers.json` | deep merge |
| `links` in `overlay.json` | any repo-relative path | symlink |
| `vars.json` | — | `${VAR}` values for JSON fragments |

Filenames must not collide with the base repo or with another overlay. `overlay.py install` refuses to apply rather than clobbering something.

## Privacy

Make this repo private if it holds anything environment-specific: employer hostnames, internal git remotes, project or ticket names, IPs, ports, account IDs, paths that identify you. That is the whole point of the split — the base repo is public and must stay generic.

`vars.json` is the one file that is committed but most likely to hold sensitive values. In a private overlay that is fine. In a public one, keep it to placeholders.

Secrets that would be damaging if leaked — passwords, API tokens, private keys — do not belong in any git repo, private ones included. Keep them in your secret store and reference them from the environment.

## Priority

`priority` in `overlay.json` decides who wins when two overlays set the same JSON key: higher wins. A personal overlay at 50 and a work overlay at 60 means work settings take precedence where they overlap.
