#!/usr/bin/env bash
# Keep this Claude pane's tmux window highlighted until the user actually replies.
# tmux clears its own bell flag as soon as the window is visited, so a glance
# loses the alert. Instead we set a per-window window-status-style that only
# goes away when we unset it, in one of three looks:
#   wait — Claude needs the user: a finished turn, a permission prompt, a question
#   seen — still needs the user, but the window has been visited since
#   bg   — the turn ended while background work runs; it will wake Claude itself
# Actions (the hook event that calls each is in settings.base.json):
#   stop   — Stop: wait, or bg when the input lists in-flight background_tasks
#   notify — Notification: wait; an idle reminder never changes an existing mark
#   clear  — UserPromptSubmit / PostToolUse / SessionEnd: the user answered or left
#   seen <window_id> — run by the tmux hook this script registers on window change
# Pending panes live per window in @claude_pending as "pane:state" words, so one
# Claude pane answering does not clear another's mark in the same window; the
# strongest state wins (wait > seen > bg). A subagent's tool call (hook input
# carries agent_id) is not the user answering. Looks are tmux options
# @claude-style-{wait,seen,bg}, appended to the global window-status-style.
# No-op outside tmux.
set -uo pipefail

command -v tmux >/dev/null 2>&1 || exit 0
action=${1:-}

if [[ "$action" == seen ]]; then
  # From a tmux hook: TMUX_PANE there is whatever the server inherited, so the
  # window comes from the hook's #{window_id} argument instead.
  target=${2:-}
  [[ -n "$target" ]] || exit 0
else
  [[ -n "${TMUX_PANE:-}" ]] || exit 0
  target=$TMUX_PANE
fi
pane=${TMUX_PANE:-}

input=""
# Claude Code writes the hook input and closes stdin; the timeout only guards a
# manual run whose stdin is a pipe that never closes.
if [[ "$action" =~ ^(stop|notify|clear)$ && ! -t 0 ]]; then
  input=$(timeout 2 cat 2>/dev/null)
fi

field() {  # field <jq filter> <grep fallback pattern>
  if command -v jq >/dev/null 2>&1; then
    printf '%s' "$input" | jq -r "$1" 2>/dev/null
  else
    printf '%s' "$input" | grep -o "$2" | head -1
  fi
}

if [[ "$action" == clear && -n "$input" ]]; then
  [[ -n "$(field '.agent_id // empty' '"agent_id" *: *"[^"]')" ]] && exit 0
fi

# "pane:state" entries of the target's window, for panes that still exist there.
entries() {
  local panes e out=""
  panes=" $(tmux list-panes -t "$target" -F '#{pane_id}' 2>/dev/null | tr '\n' ' ') "
  for e in $(tmux show-options -wqv -t "$target" @claude_pending 2>/dev/null); do
    [[ "$e" == *:* ]] || e="$e:wait"   # an entry from before states existed
    [[ "$panes" == *" ${e%%:*} "* && " $out " != *" ${e%%:*}:"* ]] || continue
    out="${out:+$out }$e"
  done
  printf '%s' "$out"
}

without() {  # without <entries> <pane>
  local e out=""
  for e in $1; do [[ "${e%%:*}" == "$2" ]] || out="${out:+$out }$e"; done
  printf '%s' "$out"
}

state_of() {  # state_of <entries> <pane>
  local e
  for e in $1; do [[ "${e%%:*}" == "$2" ]] && { printf '%s' "${e#*:}"; return; }; done
}

look() {  # look <state>
  local custom base
  custom=$(tmux show-options -gqv "@claude-style-$1" 2>/dev/null)
  if [[ -z "$custom" ]]; then
    case "$1" in
      wait) custom=$(tmux show-options -gwv window-status-bell-style 2>/dev/null)
            custom=${custom:-fg=#000000,bg=yellow,bold} ;;
      seen) custom="fg=yellow,bold" ;;
      bg)   custom="fg=colour39" ;;
    esac
  fi
  base=$(tmux show-options -gwv window-status-style 2>/dev/null)
  printf '%s' "${base:+$base,}$custom"
}

apply() {  # apply <entries>: store them and paint the strongest state
  local best="" s
  for s in wait seen bg; do
    [[ " $1 " == *":$s "* ]] && { best=$s; break; }
  done
  if [[ -z "$best" ]]; then
    tmux set-option -wu -t "$target" @claude_pending 2>/dev/null
    tmux set-option -wu -t "$target" window-status-style 2>/dev/null
  else
    tmux set-option -w -t "$target" @claude_pending "$1" 2>/dev/null || return
    tmux set-option -w -t "$target" window-status-style "$(look "$best")" 2>/dev/null
  fi
}

register_seen_hook() {  # once per tmux server: visiting a window marks it seen
  local self hook
  tmux show-hooks -g session-window-changed 2>/dev/null | grep -q 'tmux-pending' && return
  self=$(readlink -f "$0")
  hook="run-shell -b 'bash \"$self\" seen #{window_id}'"
  tmux set-hook -g 'session-window-changed[71]' "$hook" 2>/dev/null
  tmux set-hook -g 'client-session-changed[71]' "$hook" 2>/dev/null
}

visible_now() {  # is the target window on screen for an attached client?
  [[ "$(tmux display-message -p -t "$target" '#{&&:#{window_active},#{session_attached}}' 2>/dev/null)" == 1 ]]
}

current=$(entries)
case "$action" in
  stop|notify|set)
    state="wait"
    if [[ "$action" == stop ]]; then
      bg=$(field '(.background_tasks // []) | length' '"background_tasks" *: *\[ *{')
      [[ -n "$bg" && "$bg" != 0 ]] && state="bg"
    elif [[ "$action" == notify ]]; then
      # the 60-second idle reminder repeats a wait that is already marked
      [[ "$(field '.notification_type // empty' 'idle_prompt')" == idle_prompt \
         && -n "$(state_of "$current" "$pane")" ]] && exit 0
    fi
    [[ "$state" == wait ]] && visible_now && state="seen"
    register_seen_hook
    rest=$(without "$current" "$pane")
    apply "${rest:+$rest }$pane:$state"
    ;;
  clear)
    apply "$(without "$current" "$pane")"
    ;;
  seen)
    [[ -n "$current" ]] || exit 0
    marked=""
    for e in $current; do
      [[ "${e#*:}" == wait ]] && e="${e%%:*}:seen"
      marked="${marked:+$marked }$e"
    done
    apply "$marked"
    ;;
esac
exit 0
