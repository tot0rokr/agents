---
name: feedback-verify-dont-trust-manpage
description: "Man pages are a fine starting point, but when user pushes back on a \"not possible\" answer, try other sources (source code, testing) before re-asserting"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: d1080bb0-9a18-44e7-86e9-d74e6d1f6f6c
---

Man pages and official docs are useful first references, but they can be incomplete. If a user pushes back on a "not supported" / "impossible" answer, try another verification path — read the source, test the behavior, or check issue trackers — before re-asserting.

**Why:** (1) Told the user tmux `display-panes` only accepts '0'-'9' based on the man page. User said alphabets work too; source (`cmd-display-panes.c`) confirmed `a-z` map to pane index 10-35. The man page was incomplete, not wrong. (2) 2026-07-01: told the user Claude Code has no `/branch` or `/fork` slash command, twice, based on grepping the stripped native `claude` binary strings — dismissed the `branch`/`fork` matches as git/JIT noise. Wrong both times: `/branch` (switch into a conversation copy) and `/fork <directive>` (background forked subagent) are real, and the binary even contained `branchAndResume`/`createFork`/`spawnForkFromDirective`/`deriveForkName` which I misread. Official docs at code.claude.com/docs/en/commands settled it instantly.

**How to apply:** Keep docs/man pages as first source. If the user contradicts a negative claim, verify via a second path before repeating. Critically: absence-of-matches when grepping a large/minified/stripped/native binary is WEAK evidence of absence — symbol names get mangled and real features look like noise. Before asserting "feature X does not exist," cross-check the authoritative published docs (WebFetch the official reference), not just a local grep. Related: [[feedback-verify-in-user-env]].
