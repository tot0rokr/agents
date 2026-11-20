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

Where a new memory goes:

- One that holds only in the current project goes in the tool's own project memory (Claude Code: `~/.claude/projects/<project>/memory/`), which loads only in that project.
- One that holds in every project goes in [memory/](./memory/), with its line added to `memory/MEMORY.md`. If it names an employer's systems, hosts or people, it goes in that environment's overlay instead; `scripts/overlay.py route` names the overlay. See [docs/overlay.md](../docs/overlay.md).
