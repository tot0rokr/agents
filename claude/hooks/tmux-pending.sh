#!/usr/bin/env bash
# Keep this Claude pane's tmux window highlighted until the user actually replies.
# tmux clears its own bell flag as soon as the window is visited, so a glance
# loses the alert. Instead we set a per-window window-status-style (same look as
# window-status-bell-style) that only goes away when we unset it:
#   set   — Stop / Notification: Claude is waiting on the user
#   clear — UserPromptSubmit / PostToolUse: the user answered (prompt, permission, question)
# No-op outside tmux.
set -uo pipefail

[[ -n "${TMUX_PANE:-}" ]] || exit 0
command -v tmux >/dev/null 2>&1 || exit 0

case "${1:-}" in
  set)
    style=$(tmux show-options -gwv window-status-bell-style 2>/dev/null)
    tmux set-option -w -t "$TMUX_PANE" window-status-style "${style:-fg=#000000,bg=yellow,bold}" 2>/dev/null
    ;;
  clear)
    tmux set-option -wu -t "$TMUX_PANE" window-status-style 2>/dev/null
    ;;
esac
exit 0
