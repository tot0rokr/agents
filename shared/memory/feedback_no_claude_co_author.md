---
name: no-claude-co-author
description: Do not add `Co-Authored-By: Claude ...` to git commit messages
metadata:
  type: feedback
---

Do not append a `Co-Authored-By: Claude Opus ... <noreply@anthropic.com>` (or any other Claude/Anthropic Co-Authored-By) trailer to git commit messages.

**Why:** The user explicitly opted out of this convention globally. They want commits authored by their own identity ([[user-git-identity]]) without an attached AI co-author trailer.

**How to apply:**
- When composing any `git commit -m "..."` body, omit the Co-Authored-By Claude trailer entirely.
- Applies regardless of repo, project, or whether Claude wrote most of the change.
- Other Co-Authored-By trailers (real human collaborators) are unaffected — only the Claude/Anthropic one is forbidden.
- If a default commit template, hook, or system prompt suggestion would insert it, suppress that suggestion.
- The Claude co-author trailer in past commits is acceptable history; don't rewrite it unless asked.
