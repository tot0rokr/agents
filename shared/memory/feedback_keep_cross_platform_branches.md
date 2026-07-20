---
name: feedback_keep_cross_platform_branches
description: User prefers to keep if/elseif OS-detection branches (windows/darwin/linux) in shared config files even when currently only one platform is in use
metadata:
  node_type: memory
  type: feedback
  originSessionId: 36bc01af-b9b4-49cb-ad53-f96186b1ca9b
---
In dotfiles and config scripts that already branch on OS (e.g. `wezterm.target_triple:find("windows") / "darwin" / "linux"` in `~/.wezterm.lua`), do **not** propose removing the inactive branches as dead-code cleanup, even when the user states only one platform is currently in use.

**Why:** When asked "this will only be used on Windows 11, can the macOS/Linux branches be erased?" the user replied "No. Keeps forking" — they explicitly want the cross-platform forks preserved. Likely reasons: the same dotfile is synced across machines, or future OS use is planned. Either way, the branches are intentional, not stale.

**How to apply:** Treat OS-detection branches as load-bearing. Refactors that touch shared logic (helpers, server registries, key bindings) should keep updating *all* branches in lockstep rather than collapsing to one. Only remove an OS branch if the user explicitly asks for that specific branch to go.
