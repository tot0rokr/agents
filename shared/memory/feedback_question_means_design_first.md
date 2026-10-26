---
name: feedback_question_means_design_first
description: "~할 수 있어? / ~못함? / ~면 좋겠다" about building or changing something is a request for analysis + design, not a go-ahead to implement
metadata:
  type: feedback
---

When the user phrases a build/redesign idea as a question or wish ("범용으로 만들지 못함?", "없앨 수 있어?", "~구조면 좋겠는걸"), answer with analysis and a design proposal, then wait for an explicit go ("만들자", "추가해", "구현해").

**Why:** on 2026-10-07 (vdesk work) I started implementing after "범용으로 만들지 못함?" and the user stopped me mid-turn: "묻는거야. 분석하고 어떻게 설계하면될지".
**How to apply:** read-only checks (measure, grep, inspect) are fine to ground the design; no file writes, builds, or container changes until the user approves. This narrows [[feedback_act_dont_over_ask]] for design-level changes — small mechanical follow-ups still proceed.
