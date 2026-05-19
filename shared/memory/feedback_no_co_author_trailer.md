---
name: feedback-no-co-author-trailer
description: Omit the "Co-Authored-By: Claude" trailer from every git commit message — the user's repos do not want Claude attribution.
metadata:
  type: feedback
---

Do **not** append a `Co-Authored-By: Claude …` line (or any other Claude
attribution trailer) to commit messages. The user maintains repos where the
author identity should be the user alone; the default Claude Code commit
template guidance that adds this trailer is overridden by this preference.

**Why:** User said so explicitly. Their git config / repo norms treat the
commit author as the sole contributor; an extra co-author line just adds
noise and changes how blame/credits read.

**How to apply:**
- When composing any `git commit -m`, drop the `Co-Authored-By: …` line
  entirely. Commit body ends at the last meaningful paragraph.
- Same for amend / rebase --exec messages.
- Same applies if a CLI / skill (e.g. /commit) would otherwise auto-append
  it: strip before running.
- If the user later wants attribution back, they will set it themselves
  (e.g. via `attribution.commit` in `~/.claude/settings.json`).
- Note: the deterministic equivalent is `"attribution": {"commit": ""}` in
  settings.json, which prevents the harness from inserting the trailer at
  all. This memory is the heuristic backstop in case that setting is not
  in effect.
