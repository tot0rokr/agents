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

See [instructions/personal.md](./instructions/personal.md).

## Long-term memory

Persistent facts about the user, projects, and prior feedback live in
[memory/MEMORY.md](./memory/MEMORY.md). Read it when its contents are relevant
to the task at hand.
