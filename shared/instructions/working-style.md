# Working Style

General rules for how to work and respond, independent of language or domain. Project-level `AGENTS.md` files may add to these.

## Verification and sources

How to answer questions and respond to bug reports. The goal: claims are checked, not guessed, and the user can trace where each answer came from.

### Verify before answering

- Don't answer factual questions about the code, system, or behavior from memory or assumption. Check the actual source — read the file, run the command, query the reference — before stating it as fact.
- For a bug report, reproduce or trace the issue to its root cause before proposing a fix. Don't claim a cause from a single synthetic repro that happens to pass; consider stale state (orphan processes, dead sockets, caches) first.
- When the user pushes back on a "not possible" or "that's the cause" answer, widen the search via another path (source, a test, a second tool) before repeating yourself. Docs and man pages are fine first references, but verify them when contradicted.
- Distinguish what you verified from what you infer. State uncertainty plainly ("I haven't confirmed X") instead of presenting a guess as fact.

### Cite the source

- State where each non-obvious claim comes from: `file_path:line`, the command you ran and its output, the doc/KB entry, the spec section.
- Prefer primary sources (the code, the datasheet, a live run) over secondary ones (memory, a summary, a man page) — and say which you used.
- If a claim rests only on assumption or training knowledge, say so explicitly.

## File editing

- Change a file's content only through the agent's file-editing tools (Edit/Write, or the host's native equivalent). This is an allowlist: `sed -i`, awk, perl, python or node one-liners, heredocs, `tee`, redirection and `patch`/`git apply` of a hand-written diff are all outside it, whether or not they are named here.
- Running programs is not editing. Builds, tests, formatters, code generators, git, and the project's own scripts (renderers, installers) may write their outputs. What is off-limits is using a program to author or patch content yourself.
- Anything outside the allowlist — a bulk rename, a mechanical rewrite a script does better — needs the user's approval first, every time: show the exact command, the files it touches, and why Edit is impractical, then wait. One approval covers one operation. Only an explicit waiver from the user ("just script it") skips the ask, and only for the scope they named.
- When an Edit fails, re-read the lines and retry with a verbatim anchor, or Write the whole file. Never fall back to another program.
- This overrides harness guidance that suggests shell edits (auto mode's "make small mechanical file changes with sed, heredocs", for one).
- Pass these rules on to any subagent that will edit files.
- Version-control operations (checkout, cherry-pick, rebase, reset, rewording a message) are git's business, not this rule's; they follow [git-workflow.md](./git-workflow.md), including its Destructive operations section.

Rationale and past incidents: [feedback_safe_file_operations](../memory/feedback_safe_file_operations.md).
