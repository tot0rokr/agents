---
name: feedback_minimal_comments_docs_separate
description: Code comments minimal and only when needed; usage and detailed explanations belong in separate docs
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 6f63a4ac-bafe-4695-bdfc-0c08bc130c7f
---

Keep code comments clean: write a comment only when it is needed, and only the necessary content (the non-obvious intent / "why"), not tutorial-style prose narrating what the code plainly does. Move usage instructions, format specs, and detailed explanations out of inline comments into separate documentation files (e.g. a `docs/` folder).

**Why:** keeps source readable and uncluttered; details live in docs where they are discoverable and maintainable instead of duplicated across verbose comments.

**How to apply:** when writing code, comment sparingly — explain decisions/non-obvious reasoning, skip "what" narration. Put how-to-use guides and deep explanations in `docs/*.md`. Coheres with doc-cleanliness prefs [[feedback_no_bold_overuse]] and [[feedback_no_hard_wrap_markdown]].
