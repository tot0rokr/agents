# Git Workflow

## Commits

- Only commit when the user explicitly asks. Don't be over-eager.
- Prefer creating a new commit over `--amend`. Amending rewrites history and
  can lose work after a failed pre-commit hook.
- Stage files by name. Avoid `git add -A` / `git add .` — they pick up
  secrets and stray files.
- Never use `--no-verify` to skip hooks unless the user explicitly asks. If
  a hook fails, fix the underlying issue.

## Destructive operations

These need explicit user confirmation each time, even if previously approved:

- `git reset --hard`
- `git push --force` (especially to `main`/`master`)
- `git branch -D`
- `git clean -f`
- `git checkout .` / `git restore .` over uncommitted changes

## PRs

- Title under 70 characters. Put details in the body.
- Don't push to the remote unless the user asks.
