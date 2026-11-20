---
name: feedback-backup-before-destructive
description: "Before any destructive step (checkout/switch that drops files, reset, history rewrite, moving dirs aside), back up first — including unstaged and untracked state"
metadata:
  node_type: memory
  type: feedback
  originSessionId: 57c06127-d59d-4dd5-8f60-4d41c004847e
  modified: 2026-09-29T07:50:30.582Z
---

Before any destructive operation — a branch switch that deletes tracked files, `git reset`, rewriting unpushed history, moving a real directory aside so a symlink can take its place — make a backup first, and include what git cannot restore: unstaged edits, untracked files, gitignored live files (e.g. rendered `claude/settings.json`), `.git/info/exclude`. Then proceed without a further ask.

**Why:** 2026-09-29, while migrating `~/agents` from the `local` branch to overlays, the user said: "파괴적인 동작 하기 전에 백업 먼저 하고 진행하자 지금 unstaged 된것들이나 그런건 복구하기 어려울 수 있으니". Git history covers committed work only.

**How to apply:** tar the working tree's tracked + untracked files, copy each hard-to-recover file with the `.bak.<purpose>-<version>.<timestamp>` naming, save `git diff` as a patch, and create a `backup/<purpose>` branch ref before moving any branch. Verify the backup (tar listing, `cmp`) before the destructive step. See [[critical-file-safety]].
