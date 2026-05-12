---
name: bash-command-style
description: Use this skill whenever composing a shell command that chains two or more commands using &&, ||, or ;, or whenever needing to recover what the user has typed previously in their shell. Triggers include any build/install pipeline, any multi-step setup, any "do A then B then C" shell sequence, and any moment when the user references something they ran earlier that is not in the agent's conversation context. Enforces readable multi-line formatting with backslash continuations and echo separators between steps, and uses the history command to recover prior user input since history is shared across tty sessions.
---

# Bash Command Style

## Chained commands must be readable

When chaining commands with `&&`, `||`, or `;`, format them across multiple lines so each step is visible on its own line and each step's success or failure is unambiguous in the output.

Two rules:
1. Continue lines with `\` so the shell sees one command but humans see a list.
2. Insert an `echo` marker between each real step. The marker labels which command just succeeded, so when the chain fails mid-way the last printed marker pinpoints the failing step.

Example - a build pipeline:

```bash
make clean \
&& echo "[OK] make clean" \
&& ./configure --prefix=/opt/app \
&& echo "[OK] configure" \
&& make -j"$(nproc)" \
&& echo "[OK] make" \
&& sudo make install \
&& echo "[OK] make install"
```

If the chain fails between `configure` and `make`, the last printed line is `[OK] configure`, and the failure is obviously in `make`. Without the markers, you would only see compiler errors and have to guess which step produced them.

This applies to `||` and `;` chains too - the markers just describe what each step did rather than asserting success.

## Recovering user-typed commands

When the user refers to something they ran earlier ("the command I tried before", "what I just did") and that command is not in the conversation, use `history` to recover it. The shell history is shared across tty sessions, so commands typed in one terminal are visible from another.

```bash
history | tail -n 50
```

Filter for relevance instead of dumping everything:

```bash
history | grep -i <keyword> | tail -n 20
```
