---
name: feedback_act_dont_over_ask
description: user prefers I act on sensible defaults rather than stop to ask; reserve questions for real forks
metadata: 
  node_type: memory
  type: feedback
  originSessionId: e97bc2d9-2353-40e1-832f-7d3d4f9b1b02
---

On the opero project the user repeatedly signaled they don't want to be stopped with AskUserQuestion for choices that have a reasonable default — once by rejecting an AskUserQuestion outright, and by saying "바로 해"/"묻지 말고" and "좀 추가해라". They want me to pick the sensible option, state what I did, and proceed; they'll correct if wrong.

**Why:** They move fast and find confirmation prompts for low-stakes decisions annoying; a wrong guess is cheap to fix given the worktree+merge workflow.

**How to apply:** Default to acting with a brief "I chose X because…" note instead of asking. Reserve AskUserQuestion for genuine forks where the answer materially changes direction and I can't infer it (e.g. destructive/outward-facing actions, or truly ambiguous product intent). Still push/commit only when asked (see [[feedback_no_claude_co_author]] context). Relates to [[feedback_parallelize_independent_work]].
