---
name: feedback_terminal_diagrams_termaid
description: To show a diagram in a terminal reply, write a mermaid code block, which the termaid plugin draws in place in Claude Code; when the text itself must be the picture (other agents, code blocks and comments, docs, commit or PR text), render the Mermaid with the termaid CLI instead of drawing box art by hand
metadata:
  type: feedback
---

termaid (https://github.com/fasouto/termaid, MIT) draws Mermaid as Unicode box drawing or plain ASCII. The harness base installs two parts:
- The Claude Code plugin `termaid@termaid`, from the marketplace `fasouto/termaid`, enabled in `base/settings/claude.json`. Its `MessageDisplay` hook replaces each ```mermaid block in Claude's reply with the drawing, fitted to the pane width. Only the screen changes; the transcript keeps the Mermaid source.
- The CLI `termaid`, which the base setup step `termaid-cli` (in `base/overlay.json`) installs with `uv tool install termaid==0.12.0`. Every agent can run it.

How to show a diagram:
- **In a Claude Code reply:** write a ```mermaid code block and stop there. Don't also run termaid on it and paste the output, or the diagram shows twice. Don't hand-draw box art in a reply.
- **Where no hook draws it, or where the text itself must be the drawing:** render the Mermaid with the CLI and paste the output verbatim in a fenced code block.
  - Where: Codex, Gemini CLI and OpenCode replies; a code block or code comment; a Markdown document that wants an ASCII figure under the Diagrams section of `shared/instructions/doc-writing.md`; a commit message or PR body.
  - Command: `printf '%s\n' '<mermaid source>' | termaid --width 100`
  - Width: the Bash tool is not a terminal, so always pass `--width`. Use 100, less for a narrow pane, and 72 for a commit message.
  - ASCII: add `--ascii` where the text should stay 7-bit, such as source code comments and commit messages.
- **Diagrams that already exist** in a file or document: `termaid --width 100 diagram.mmd`, or `termaid --width 100 --markdown README.md` for every block in a document. In Claude Code the plugin's `/termaid:mermaid` skill does the same.
- termaid parses leniently, so a drawing does not prove the Mermaid is valid. Compare the drawing with the nodes and edges you meant before handing it over. When it cannot draw anything, it exits non-zero and prints the reason on stderr.
- If `termaid` is not on `PATH`, say so and offer to run `scripts/overlay.py setup base --only termaid-cli --yes`. Don't fall back to hand-drawn art without saying so.

Polished images and shareable pages still follow [[feedback_diagram_skill_routing]] (diagram-design, archify).

**Why:** On 2026-11-08 the user asked that diagrams shown in Claude's terminal replies be drawn with this terminal Mermaid renderer, and that it be used whenever a terminal ASCII picture is needed. On 2026-11-20 the user moved it from the personal overlay into the base, so every machine gets it.

**How to apply:** Before drawing anything in text, write it as Mermaid. In a Claude Code reply, leave it to the hook; everywhere else, render it with the CLI and paste the output.
