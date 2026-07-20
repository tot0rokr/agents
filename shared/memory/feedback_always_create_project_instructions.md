---
name: feedback_always_create_project_instructions
description: When creating/scaffolding a new project, always add a project-level instructions file, not just rely on the global one
metadata:
  node_type: memory
  type: feedback
  originSessionId: 37dde53f-f8ab-4bb0-8cb0-2c38d8441688
---

When creating or scaffolding a new project (a new git repo / codebase), always create a project-level instructions file at the repo root (`CLAUDE.md`; tool-neutral so Codex/Gemini/OpenCode can share it too). Do not rely on the global `~/.claude/CLAUDE.md` alone.

**Why:** all instruction files load together and are additive — a project file never deletes the global one, they coexist. A project file lets project-specific rules take precedence on genuine conflict and, more importantly, makes intent explicit instead of leaving the model to infer it. It is also team-shareable since it lives in the repo.

**How to apply:** at project init/scaffold time, write `CLAUDE.md` capturing project-specific conventions (build/test commands, structure, hard constraints). State explicitly where it should override default behavior. Keep it thin and link to detailed docs rather than inlining everything (coheres with [[feedback_minimal_comments_docs_separate]]).
