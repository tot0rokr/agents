# Git Workflow

## Commits

- Only commit when the user explicitly asks. Don't be over-eager.
- Prefer creating a new commit over `--amend`. Amending rewrites history and
  can lose work after a failed pre-commit hook.
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

- When writing in English, keep it simple and plain: use common words, direct phrasing, and short sentences. Prefer "Fix crash when the buffer is empty" over "Remediate the anomalous termination occurring upon buffer vacancy".
- Subject line in the imperative mood, under ~70 characters. Put the why and any detail in the body.

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
