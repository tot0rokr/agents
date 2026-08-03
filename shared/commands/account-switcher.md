---
description: Run a claude-auto account-switcher command inside this session (status, switch, priority, …)
argument-hint: "<subcommand> [args] — status | switch <name> | priority <name…> | scheduler <mode> | whoami | plan | relabel | remove <name> | save | clear"
---

Run the `claude-auto` account-switcher with the given arguments. Requested: `$ARGUMENTS`

Rules:
1. If `$ARGUMENTS` is empty, run `claude-auto status` (the default view).
2. Allowed subcommands: `status`, `switch`, `use`, `unpin`, `whoami`, `plan`, `relabel`, `remove`, `save`, `clear`, `refresh`, `scheduler`, `priority`, `version`, `help`. Run `claude-auto $ARGUMENTS` and show its output verbatim.
3. Do NOT run `login` or a bare launch here — that needs an interactive terminal (OAuth). If asked, tell the user to run `claude-auto login <name>` in a shell instead, and stop.
4. After a `switch`, `priority`, or `scheduler` change, briefly confirm the resulting active account / order / mode.

Run exactly one `claude-auto` invocation. Do not start a Claude session or run unrelated commands. If `claude-auto` is not on PATH, say so and stop.
