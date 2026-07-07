---
name: project_grep_find_rg_fd_wrappers
description: "User's interactive shell aliases grep/find to rg/fd-translating wrapper functions"
metadata: 
  node_type: memory
  type: project
  originSessionId: b9354deb-291a-40d0-b9a6-6134a8e5d165
---

The user finds `grep`/`find` slow and prefers `rg`/`fd`. In their interactive bash, `grep` and `find` are now shell **functions** (defined in `~/.config/shell/modern-grep-find.bash`, sourced from `~/.bashrc`) that translate common invocations to `rg`/`fd` and transparently `exec` the real tool for anything unrecognized (e.g. grep `-G`/BRE, find `-newer`/`-mtime`/`-size`/`-empty`/`!`/`-o`).

Key points:
- **Interactive-only** (the file self-guards on `$-`), so scripts/`sh -c`/make/CI keep real grep/find. My own non-interactive Bash tool calls are NOT affected.
- **Faithful by default**: rg/fd get `--no-ignore --hidden` so results match real grep/find. `MODERN_GF_IGNORE=1` opts into rg/fd default filtering (respect .gitignore, skip hidden). Note rg only honors `.gitignore` inside a git repo.
- Per-call bypass: `command grep ...` / `command find ...`. Disable all: `unset -f grep find`.
- The file self-`unalias`es grep/find before defining the functions, because a pre-existing `alias grep='grep --color=auto'` would otherwise break the function definition with a syntax error.

So if the user ever reports grep/find "behaving differently" interactively, suspect these wrappers first.
