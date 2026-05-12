---
name: git-commit-workflow
description: Use this skill whenever about to run git commit, compose a commit message, or invoke any destructive git operation such as git reset, git restore, git checkout -- <file>, git clean, or any history-rewriting command (rebase, amend, push --force). Triggers also include staging changes with git add and any moment the agent has modified files inside a git-managed repository. Enforces commit hygiene (only commit what this agent changed, base the message on actual git status and git diff output) and a hard stop before any destructive operation that could lose user work.
---

# Git Commit Workflow

## Commit only what this agent changed

A git repository often contains modifications from the user or previous agent sessions that are unrelated to the current task. Sweeping those into a commit produces misleading history.

Before committing:
1. Run `git status` to see every modified, staged, untracked, and deleted file in the working tree.
2. Identify which files this agent actually touched in the current session. If unsure, cross-check against the conversation.
3. Stage *only* those files explicitly by path. Avoid `git add .` and `git add -A` unless every change in the tree was made by this agent.

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
