---
name: user_git_identity
description: "Which git author/committer identity to use per git domain — company vs personal, with a fallback rule for unknown domains"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 1c31f6c1-6d9c-458b-8170-b548a86a8bf7
---

When making commits or signing, pick the git identity by the remote's git domain — do NOT ask when the domain is already known:

- Enterprise GitHub (`<enterprise-gh-host>`, and other `*.<enterprise-domain>`): always use the work account `<Work Name> <work-email@company.tld>`.
- Personal GitHub (`github.com`): always use the personal account `<Personal Name> <personal-email@example.com>` (personal GitHub username: `<personal-gh-username>`).

**Why:** The user keeps work and personal contribution history strictly separated by domain; a commit under the wrong identity on the wrong host is annoying to fix and leaks the wrong email.

**How to apply:** Set the identity with repo-local `git config` (never `--global`) per [[feedback_always_use_worktree]]. If a repo's git domain or project is NOT covered by a rule in memory, ask the user which identity to use, then record that domain→identity mapping in this file so it's deterministic next time. This is local memory only — do NOT push/commit these identity notes to GitHub or to the agents repo.
