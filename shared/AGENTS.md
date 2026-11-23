# Agent Instructions

This file is the single source of truth for cross-agent behavior. It is
referenced (via symlink) by Claude Code, Codex CLI, OpenCode, and Gemini CLI,
so keep it tool-neutral.

Keep this file thin. Put detailed rules under `instructions/` and link to them
from here.

## Language

See [instructions/language.md](./instructions/language.md).

## Working style

See [instructions/working-style.md](./instructions/working-style.md).

## Parallelism & orchestration

See [instructions/orchestration.md](./instructions/orchestration.md).

## Coding style

See [instructions/coding-style.md](./instructions/coding-style.md).

## Git workflow

See [instructions/git-workflow.md](./instructions/git-workflow.md).

## Document writing

See [instructions/doc-writing.md](./instructions/doc-writing.md).

## Notifications

See [instructions/notifications.md](./instructions/notifications.md).

## Personal context

See [instructions/personal.md](./instructions/personal.md) — supplied by an overlay, so it is absent on a machine that has none. See [docs/overlay.md](../docs/overlay.md).

## Long-term memory

The user's preferences and the rules that hold in every project live in the shared memory pool, [memory/](./memory/). Its index follows; open a memory file when its line is relevant to the task at hand.

@memory/MEMORY.md

## Where new content goes

Decide who owns a new memory, skill, instruction, command, subagent, settings fragment or MCP server before writing it. Paths below are relative to the harness repo (`~/agents`).

| The content | Goes in |
|---|---|
| holds only in the current project | the tool's own project memory (Claude Code: `~/.claude/projects/<project>/memory/`), which loads only in that project |
| holds in every project and names nothing environment-specific | the base, this repo, which is public |
| names an employer's systems, hosts, internal repos, people or tickets | that environment's overlay; `scripts/overlay.py route` names it |
| is about the user personally: identity, personal machines and accounts | the personal overlay |
| holds on one machine only | the overlay of the environment that machine belongs to, with its index line in that overlay's `memory/hosts/<host>.md`, which joins the index on that machine alone (`overlay.py file <path> --to <alias> --host <host>`) |
| is a credential | no git repo at all: a machine-local file or an environment variable |

- When unsure, use an overlay (private), never the base.
- File it with `scripts/overlay.py file <path> --to base|<alias>`: it stages the file in the right repo and moves its index line to the right index source. Commit afterwards, in that repo. By hand, a memory's index line goes in `base/memory/MEMORY.md` for the base or `overlays/<alias>/memory/MEMORY.md` for an overlay; `shared/memory/MEMORY.md` is rendered, so a line added there is not filed.
- `scripts/overlay.py status` lists anything in the view directories that nobody tracks as `UNFILED`.
- Before committing to the base, read the diff for hostnames, IPs, internal URLs, user names and ticket IDs. A hook refuses a base commit of a path an overlay provides. See [docs/overlay.md](../docs/overlay.md).
