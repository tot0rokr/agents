# Git Workflow

## Commits

- Only commit when the user explicitly asks. Don't be over-eager.
- Make a new commit instead of `--amend` unless the user asks for an amend.
  Amending rewrites history and can lose work after a failed pre-commit hook.
- Stage files by name. Avoid `git add -A` / `git add .` — they pick up
  secrets and stray files.
- Never use `--no-verify` to skip hooks unless the user explicitly asks. If
  a hook fails, fix the underlying issue.

## Pushing — never push unless asked in the moment

Treat this as a hard rule, not a default. A push sends work to a remote: it is outward-facing and hard to take back, so the user wants to control every push personally.

- Never push on your own initiative. `git push` runs ONLY when the user tells you to push in that same turn. Committing — even when a commit is the natural next step — is never permission to push.
- Approval does not carry over. One "push" covers that one push, not later commits; a push earlier in the session is not standing consent. Each push needs a fresh, in-the-moment instruction.
- First push of a branch when more than one remote exists: run `git remote -v`, then ask which remote to push to before pushing.
- `git push --force` needs explicit confirmation each time on top of the above — see Destructive operations.

## Commit messages

How to stage and write a commit (format, subject length, body, plain English) is in the `git-commit-workflow` skill (`universal/skills/git-commit-workflow/SKILL.md`). The language per remote is in [language.md](./language.md).

## Destructive operations

This is the one list; the `git-commit-workflow` skill points here. Each of these needs the user's explicit approval for that run, every time, even if it was approved before in this session or in a record. Name the exact command and the files or refs it affects, then wait.

- `git reset` in any mode (`--hard` discards work; `--soft` and `--mixed` move the branch)
- Anything that overwrites the working tree over uncommitted changes: `git restore` without `--staged` (including `--worktree` and `--source=<ref>`), `git checkout .`, `git checkout -- <file>`, `git checkout <ref> -- <file>`
- `git clean` in any form
- `git rebase`, and `git commit --amend` on commits that were already pushed
- `git push --force` and `--force-with-lease` (especially to `main`/`master`)
- `git branch -D`, `git tag -d`

`git restore --staged <path>` on its own only unstages and leaves the working tree untouched, so it is fine for undoing your own staging.

## PRs

- Title under 70 characters. Put details in the body.
- Don't push to the remote unless the user asks.
