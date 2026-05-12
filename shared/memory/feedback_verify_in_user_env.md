---
name: Verify fix in user's actual environment
description: Don't claim a fix worked from a single synthetic reproduction — verify in the user's real session, especially when their original repro was intermittent
type: feedback
originSessionId: 25e70a62-a9ad-4847-8a12-1f223d9edf71
---
When diagnosing a crash/hang the user reports, do NOT declare a root cause from one successful synthetic reproduction (e.g., a fresh `tmux new-session -d` started by my own Bash tool). The user's environment carries state — orphan/zombie processes, stale sockets, prior session env — that controlled reproductions don't have.

**Why:** In one session I told the user "airline is the culprit" after commenting it out and seeing my own fresh-tmux test pass. The user retested in their real terminal and it still crashed — actual cause was accumulated orphan `nvim --embed` processes + dead tmux server socket from earlier crashes. A terminal/SSH restart fixed it. I had no business claiming airline was at fault.

**How to apply:**
- When the original repro was intermittent and my fresh-env test passes, treat that as "couldn't reproduce," not "fixed."
- If orphan/zombie processes from prior failures are visible (e.g., `pgrep` shows leftovers, deleted-pty fds), suggest cleaning state (kill orphans, restart terminal/tmux) BEFORE concluding it's a config bug.
- Don't edit the user's config based on a hypothesis I haven't confirmed they can reproduce. Ask first, or run the test in a way that matches their actual invocation (their attached tmux client, not a detached one I spawn).
- State confidence honestly: "my test passed but yours might differ — try this and tell me what you see" rather than "X is the cause."
