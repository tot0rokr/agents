---
name: feedback_diagram_skill_routing
description: Two diagram skills are installed; diagram-design for polished static figures and branching or complex flows, archify for repo-backed, maintained, interactive diagrams; with diagram-design never drop what the user named, split into more figures instead
metadata:
  type: feedback
---

Both `diagram-design` and `archify` are installed, and both trigger on architecture, sequence and flow requests. Pick one by what the reader needs before loading either skill, and state the choice in one line.

For a figure that goes into a document, the format comes first from the Diagrams section of `shared/instructions/doc-writing.md`: ASCII inside code blocks and code comments, an image drawn with one of these skills (SVG, WebP, PNG or JPEG) when the document can attach images, otherwise Mermaid where it renders, or an image made with a Mermaid renderer. The table below picks the tool once the answer is an image or a page.

| Request | Use | Why |
|---|---|---|
| Sequence or state flow with branches, error paths or timeouts (auth flows, protocol updates such as PLDM) | diagram-design | ALT fragments, self-messages and composite state frames; it splits an over-budget request into a sequence plus a state machine. archify's sequence has no alt/opt, so branches read as consecutive steps and error paths end up in text cards. |
| Complex request where every listed item must appear in the drawing | diagram-design | It splits into several figures instead of moving content into prose cards. |
| One-off figure for a doc, slide, print or blog; charts and data visuals | diagram-design | Best look, 17-45 KB, no JavaScript, 45 types including charts. Light theme only, small type. |
| Diagram grounded in a repository and kept up to date | archify | Repository-backed mode cites line ranges at a pinned commit, and the JSON source re-renders through validation. Commit `candidate.json` next to the HTML. |
| Page shared with others: dark mode, zoom, search, export; a one-screen architecture overview; a one-page answer to a question (explainer) | archify | The only one with themes, navigation and in-page export; one offline file of about 850 KB. |
| Docs in Git that change every sprint | archify (or Mermaid) | Diffable source; diagram-design has no editable source. |

If it is unclear, ask which matters more: the look of one figure (diagram-design), or keeping it accurate and explorable over time (archify).

With diagram-design:
- Never drop or merge an actor, step, state or path the user named just to stay under the skill's budgets (9 nodes, 12 arrows or messages, 5 lifelines, 14-character arrow labels). When the content exceeds a budget, split it into several figures on one page, as the skill's own overview + detail rule says, even when the user asked for "one diagram", and say on the page that it was split.
- If splitting still cannot hold it, exceed the budget rather than omit content, and tell the user which budget you exceeded.

With archify:
- Check that nothing the user asked to see ended up only in a text card. If it did, draw it or say so.
- `finalize` must exit 0, but its gates have passed visible defects, so look at the render anyway.
- `finalize` needs Chrome or Chromium on `PATH` (or `ARCHIFY_CHROME`). Repository mode needs an HTTP(S) or SSH `origin`; a `file://` clone is rejected.

With both: look at a screenshot before handing the diagram over.

If archify offers to make one-page explainers proactive and the user accepts, add its one-line `[archify explainer: ...]` rule to `shared/AGENTS.md`, the global rules file every tool reads (`~/.claude/CLAUDE.md` and `~/.codex/AGENTS.md` both link to it). Keep it to that one line.

**Why:** In a 2026-11-04 comparison (4 scenarios x 2 tools, judged on fidelity, visual quality and practicality), archify won the simple requests because diagram-design's budgets cut content even there (one run dropped the User actor). diagram-design won the complex ones because it split into figures while archify pushed error paths and symlinks into cards. diagram-design won visual quality 4 of 4 and archify won practicality 4 of 4. The user chose this memory rule over patching diagram-design's budgets.

**How to apply:** Route by the table before loading a skill. For diagram-design, plan the split up front when the request lists more than the budget allows.
