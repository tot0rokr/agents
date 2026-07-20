---
name: feedback_no_claude_co_author
description: Do not add a `Co-Authored-By: Claude ...` trailer to git commit messages — the user wants sole authorship
metadata:
  node_type: memory
  type: feedback
---

Do not append a `Co-Authored-By: Claude ... <noreply@anthropic.com>` (or any other Claude/Anthropic Co-Authored-By) trailer to git commit messages. The user maintains repos where the author identity should be the user alone, and has opted out of this convention globally.

**Why:** The user said so explicitly. Their git config / repo norms treat the commit author as the sole contributor ([[user_git_identity]]); an extra co-author line just adds noise and changes how blame/credit read.

**How to apply:**
- When composing any `git commit -m "..."` body, omit the Co-Authored-By Claude trailer entirely. The commit body ends at the last meaningful paragraph.
- Same for `amend` / `rebase --exec` messages.
- Applies regardless of repo, project, or whether Claude wrote most of the change.
- If a default commit template, hook, or skill (e.g. `/commit`) would otherwise auto-append it, suppress/strip that before running.
- Other Co-Authored-By trailers (real human collaborators) are unaffected — only the Claude/Anthropic one is forbidden.
- Deterministic equivalent: `"attribution": {"commit": ""}` in `~/.claude/settings.json` stops the harness from inserting the trailer at all. This memory is the heuristic backstop in case that setting is not in effect. If the user later wants attribution back, they will set it themselves.
- The Claude co-author trailer in past commits is acceptable history; don't rewrite it unless asked.
