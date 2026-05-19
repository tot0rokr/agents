---
name: feedback-verify-dont-trust-manpage
description: "Man pages are a fine starting point, but when user pushes back on a \"not possible\" answer, try other sources (source code, testing) before re-asserting"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: d1080bb0-9a18-44e7-86e9-d74e6d1f6f6c
---

Man pages and official docs are useful first references, but they can be incomplete. If a user pushes back on a "not supported" / "impossible" answer, try another verification path — read the source, test the behavior, or check issue trackers — before re-asserting.

**Why:** Told the user tmux `display-panes` only accepts '0'-'9' based on the man page. User said alphabets work too; source (`cmd-display-panes.c`) confirmed `a-z` map to pane index 10-35. The man page was incomplete, not wrong. Lesson is to widen the search when contradicted, not to distrust docs by default.

**How to apply:** Keep using man pages / official docs as the first source. But if the user contradicts a negative claim, treat it as a signal to verify via a second path before repeating the claim. Related: [[feedback-verify-in-user-env]].
