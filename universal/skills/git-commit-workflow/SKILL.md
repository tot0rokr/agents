---
name: git-commit-workflow
description: Use this skill whenever about to run git commit, compose a commit message, or invoke any destructive git operation such as git reset, git restore, git checkout -- <file>, git clean, or any history-rewriting command (rebase, amend, push --force). Triggers also include staging changes with git add and any moment the agent has modified files inside a git-managed repository. Enforces commit hygiene (only commit what this agent changed, base the message on actual git status and git diff output) and a hard stop before any destructive operation that could lose user work.
---

# Git Commit Workflow

## Stage only what THIS work changed

A working tree often contains modifications from earlier sessions, the user's own hand-edits, or other agents. Sweeping everything in produces commits that mix unrelated work and — worse — can publish files the user deliberately kept out of git (memory snippets containing secrets, in-progress drafts, local-only configs). The verification procedure below is mandatory before every `git add`.

### Required procedure before staging

1. **Inventory the current state.** Run these in order and read every line of every output:

   ```bash
   git status --short
   git diff
   git diff --staged   # only if anything is already staged
   ```

   `git status --short` lists every modified, staged, untracked, and deleted path. The diffs show the actual content changes. You need all three to know what's there.

2. **Classify each entry.** For every path in `git status --short`, decide which bucket it belongs to:
   - **This work** — a file this agent changed in service of the current task. Goes into the commit.
   - **Pre-existing / unrelated** — modified before this session, or by another tool (e.g. a plugin migrated its own config). Stays out.
   - **Deliberately uncommitted** — the user said "don't commit this", or it's known working-tree-only state (e.g. memory files with PII, `*.local.json`). Stays out.
   - **Unsure** — stop and ask the user before staging. Don't guess.

3. **Stage by explicit path.** Always:

   ```bash
   git add path/to/specific-file.py path/to/other-file.md
   ```

   **Forbidden — no exceptions**: `git add -A`, `git add .`, `git add -u`, `git add :/`, or any glob that could absorb unrelated changes. If the file list is long, list every path on its own line; the verbosity is the point.

4. **Verify staging matches intent.** After staging, run `git status --short` once more and `git diff --staged` again. Compare what's staged to your bucket-1 list from step 2. If anything else snuck in, `git restore --staged <path>` it and re-verify.

### Failure mode this rule blocks

A typical violation: the agent is doing a tree-wide rename or refactor and reaches for `git add -A` so the renames register correctly. That command also stages every other modified file in the tree, including any memory or note file the user is keeping working-tree-only. Once committed and pushed (especially to a public repo), the leaked file is in history — force-push only partially scrubs it. **Stage the rename explicitly**: list the old and new paths, the imports, the config, the tests. Verbose is correct.

## Write the message from the diff, not from memory

The commit message must describe what is actually being committed, not what the agent intended to do. Before writing the message:

```bash
git status \
&& echo "--- staged diff ---" \
&& git diff --staged
```

Read the staged diff and write the message from what is actually there. If the diff and the intended change disagree, fix the staging before writing the message.

## Multi-line messages: stacked -m flags with line continuations

For commit messages spanning multiple lines, use repeated `-m` flags rather than opening an editor or embedding newlines in a single quoted string. Use `\` to continue the command across lines so the message structure is visible:

```bash
git commit \
  -m "subsystem: short imperative summary" \
  -m "" \
  -m "Explain what changed and why. Reference the problem this" \
  -m "addresses and any non-obvious decisions." \
  -m "" \
  -m "Refs: #123"
```

Each `-m` becomes a paragraph separated by a blank line in the final message. The empty `-m ""` flags produce the blank-line separators that git's commit format expects between subject and body.

## Destructive operations require explicit user approval

Never invoke any of these without the user explicitly asking for them in the current session:

- `git reset` (any mode, especially `--hard`)
- `git restore` (any flags)
- `git checkout -- <file>` or `git checkout <ref> -- <file>`
- `git clean`
- `git rebase`, `git commit --amend` on already-pushed commits
- `git push --force` or `--force-with-lease`
- `git branch -D`, `git tag -d`

If one of these seems necessary, stop and ask the user, naming the exact command and the files or refs it would affect. Wait for an explicit go-ahead before running it.
