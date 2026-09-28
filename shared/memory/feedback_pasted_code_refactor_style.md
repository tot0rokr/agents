---
name: pasted-code-refactor-style
description: "When the user pastes code for a rewrite, work from the paste (don't hunt the repo) and preserve the file's existing style (top-of-function declarations, if/else stays if/else)"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: afc5f79f-9177-44e8-9b24-8ae1b6924ea9
  modified: 2026-09-21T08:03:19.946Z
---

When the user pastes a code snippet and asks for a rewrite/cleanup, work directly on the pasted text. Don't search the filesystem for the source file unless asked; if the paste is truncated, ask for the rest. Keep the snippet's own conventions: top-of-function variable declarations, Yoda conditions (`NULL == x`, `FALSE == y`), and don't convert an if/else into a ternary. "구조적으로" means reduce duplication and branch count without changing evaluation order, side effects, or return values.

**Why:** User rejected a repo-wide `rg` for the pasted function and supplied the full text instead (2026-09-21). They then asked to restore the top-declaration style and undo an if/else→ternary change.

**How to apply:** Refactor requests on pasted code: no filesystem search, no logic change, match the paste's declaration and conditional style, and answer "can branches be reduced further" honestly with the behavior trade-off. Related: [[act-on-sensible-defaults]], [[minimal-comments-docs-separate]].
