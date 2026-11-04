---
name: feedback_retry_git_auth_failures
description: When git push/pull/fetch or a gh command fails with an authentication or connection error, retry the same command up to 3 times one minute apart before reporting; these failures are often transient
metadata:
  type: feedback
---

If `git push`, `git pull`, `git fetch`, `git ls-remote`, `git clone` or a `gh` command fails with an authentication or connection error, retry the same command up to 3 more times, one minute apart, before reporting the failure. Typical messages: `Invalid username or token`, `Authentication failed`, `Bad credentials`, HTTP 401/403 from the host, `Could not resolve host`, timeouts, connection reset.

- Run the retries as one shell loop in the background and wait for its completion notice instead of polling, e.g. `for i in 1 2 3; do git push origin main && break; sleep 60; done`.
- Retry only the same command. A push retry is still the push the user asked for; it does not extend to other repos or later commits.
- Don't retry rejections that waiting will not change: non-fast-forward, protected branch, failed hooks, merge conflicts.
- Don't touch credentials while retrying: no reading or printing tokens, no inspecting credential stores, no logging in or rewriting git/gh auth config.
- After the last failure, stop, report the exact error, and suggest the user check or refresh the login for that host.

**Why:** The user has seen these commands fail with auth errors and work again later (github.com `Invalid username or token`, 2026-11-04; the company GHE answered 403 for a while earlier). They asked for automatic retries (2026-11-04).

**How to apply:** Treat the first auth or connection failure as possibly transient. Say it failed only after the retries.
