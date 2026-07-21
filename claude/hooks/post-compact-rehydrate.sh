#!/usr/bin/env bash
# SessionStart(compact) hook: after a compaction reopens the session, instruct
# the agent to re-read the prior conversation and rebuild working context to
# ~30% before continuing.
#
# Reads the SessionStart hook JSON on stdin, emits {hookSpecificOutput.additionalContext}
# on stdout so the directive is injected into the model's context every compaction.
# (PostCompact cannot inject additionalContext — only SessionStart/compact can.)
set -uo pipefail

input="$(cat 2>/dev/null || true)"
transcript="$(printf '%s' "$input" | jq -r '.transcript_path // empty' 2>/dev/null || true)"

directive="A compaction just occurred — your detailed conversation history was replaced by a short summary. Before doing ANYTHING else, carefully re-read the prior conversation to rebuild working context: refill roughly 30% of your context window with the most relevant prior detail (user preferences and feedback, decisions made, files created/edited and where, and any open or unfinished threads), prioritizing the most recent turns, and stop before you overflow. Do not take new actions until you have done this."

if [ -n "${transcript:-}" ]; then
  directive="${directive} The full session transcript is on disk at: ${transcript} — read the relevant tail of it (not necessarily the whole file) to reconstruct that context."
fi

jq -cn --arg ctx "$directive" '{hookSpecificOutput:{hookEventName:"SessionStart",additionalContext:$ctx}}'
