#!/usr/bin/env bash
# Keep this Claude pane's tmux window highlighted until the user actually replies.
# tmux clears its own bell flag as soon as the window is visited, so a glance
# loses the alert. Instead we set a per-window window-status-style (same look as
# window-status-bell-style) that only goes away when we unset it:
#   set   — Stop / Notification: Claude is waiting on the user
#   clear — UserPromptSubmit / PostToolUse / SessionEnd: the user answered or left
# Pending panes are tracked per window in @claude_pending, so one Claude pane
# answering does not clear another pane's highlight in the same window. A
# subagent's tool call (hook input carries agent_id) is not the user answering.
# No-op outside tmux.
set -uo pipefail

[[ -n "${TMUX_PANE:-}" ]] || exit 0
command -v tmux >/dev/null 2>&1 || exit 0

pane=$TMUX_PANE
action=${1:-}
input=""
# Claude Code writes the hook input and closes stdin; the timeout only guards a
# manual run whose stdin is a pipe that never closes.
[[ "$action" == clear && ! -t 0 ]] && input=$(timeout 2 cat 2>/dev/null)

if [[ -n "$input" ]]; then
  if command -v jq >/dev/null 2>&1; then
    agent=$(printf '%s' "$input" | jq -r '.agent_id // empty' 2>/dev/null)
  else
    agent=$(printf '%s' "$input" | grep -o '"agent_id" *: *"[^"]' || true)
  fi
  [[ -n "$agent" ]] && exit 0
fi

# Pending panes that still exist in this window, minus $1 if given.
live_pending() {
  local drop=${1:-} p out=""
  local panes
  panes=" $(tmux list-panes -t "$pane" -F '#{pane_id}' 2>/dev/null | tr '\n' ' ') "
  for p in $(tmux show-options -wqv -t "$pane" @claude_pending 2>/dev/null); do
    [[ "$p" == "$drop" || "$panes" != *" $p "* || " $out " == *" $p "* ]] && continue
    out="${out:+$out }$p"
  done
  printf '%s' "$out"
}

case "$action" in
  set)
    pending=$(live_pending "$pane")
    tmux set-option -w -t "$pane" @claude_pending "${pending:+$pending }$pane" 2>/dev/null || exit 0
    style=$(tmux show-options -gwv window-status-bell-style 2>/dev/null)
    tmux set-option -w -t "$pane" window-status-style "${style:-fg=#000000,bg=yellow,bold}" 2>/dev/null
    ;;
  clear)
    pending=$(live_pending "$pane")
    if [[ -n "$pending" ]]; then
      tmux set-option -w -t "$pane" @claude_pending "$pending" 2>/dev/null
    else
      tmux set-option -wu -t "$pane" @claude_pending 2>/dev/null
      tmux set-option -wu -t "$pane" window-status-style 2>/dev/null
    fi
    ;;
esac
exit 0
