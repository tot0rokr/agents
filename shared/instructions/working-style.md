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
