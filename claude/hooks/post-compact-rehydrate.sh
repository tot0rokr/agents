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
session_id="$(printf '%s' "$input" | jq -r '.session_id // empty' 2>/dev/null || true)"

directive="A compaction just occurred — your detailed conversation history was replaced by a short summary. Before doing ANYTHING else, carefully re-read the prior conversation to rebuild working context: refill roughly 30% of your context window with the most relevant prior detail (user preferences and feedback, decisions made, files created/edited and where, and any open or unfinished threads), prioritizing the most recent turns, and stop before you overflow. Do not take new actions until you have done this."

if [ -n "${transcript:-}" ]; then
  directive="${directive} The full session transcript is on disk at: ${transcript} — read the relevant tail of it (not necessarily the whole file) to reconstruct that context."
fi

# pre-compact-branch.sh snapshots the full pre-compact conversation into a new
# resumable session; surface the latest snapshot for this session, if any.
registry="$HOME/.claude/hooks/state/precompact-branches.jsonl"
if [ -n "${session_id:-}" ] && [ -f "$registry" ]; then
  snap_line="$(jq -c --arg sid "$session_id" 'select(.orig==$sid)' "$registry" 2>/dev/null | tail -1)"
  if [ -n "${snap_line:-}" ]; then
    snap_id="$(jq -r '.snapshot // empty' <<<"$snap_line" 2>/dev/null)"
    snap_title="$(jq -r '.title // empty' <<<"$snap_line" 2>/dev/null)"
    if [ -n "$snap_id" ]; then
      directive="${directive} Additionally, the complete pre-compact conversation (including /rewind checkpoints) was preserved as a separate session: ${snap_id} (titled \"${snap_title}\", stored in a *-precompact-snapshots project bucket so it never collides with the live session). If the user asks to go back to something from before the compaction, tell them to open it with: claude --resume ${snap_id} (or /resume, then Ctrl+A for all projects — note snapshots sort by their original conversation date, not the snapshot time, so search or scroll)."
    fi
  fi
fi

jq -cn --arg ctx "$directive" '{hookSpecificOutput:{hookEventName:"SessionStart",additionalContext:$ctx}}'
