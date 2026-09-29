#!/usr/bin/env bash
# Keep this Claude pane's tmux window highlighted until the user actually replies.
# tmux clears its own bell flag as soon as the window is visited, so a glance
# loses the alert. Instead we set a per-window window-status-style that only
# goes away when we unset it, in one of four looks:
#   wait — Claude needs the user: a finished turn, a permission prompt, a question,
#          an interrupted or failed turn
#   seen — still needs the user, but the window has been visited since
#   bg   — the turn ended while background work runs; it will wake Claude itself
#   work — Claude is working on a turn
# Actions (the hook event that calls each is in settings.base.json):
#   stop   — Stop / StopFailure: wait, or bg when the input lists in-flight
#            background_tasks
#   notify — Notification: wait. The 60-second idle reminder keeps an existing
#            mark, except work, which it turns into wait
#   work   — UserPromptSubmit / PostToolUse: Claude is working; also starts the
#            watcher below
#   clear  — SessionEnd: the session is gone
#   seen <window_id> — run by the tmux hook this script registers on window
#            change; also sweeps marks left by Claude processes that died
#   watch  — internal, one per marked pane: polls the pane's footer, which says
#            "esc to interrupt" exactly while a turn runs. Esc and Ctrl+C stop a
#            turn without any hook (the transcript only records it with the next
#            prompt), so work whose footer went quiet becomes wait; a wait whose
#            footer comes back (a granted permission) becomes work
# Marks live per window in @claude_pending as "pane:state:pid" words; pid is the
# Claude process, so a mark whose Claude was killed (no SessionEnd) is dropped.
# One Claude pane answering does not clear another's mark in the same window;
# the strongest state wins (wait > seen > bg > work). A subagent's tool call
# (hook input carries agent_id) is not the user answering. Looks are tmux
# options @claude-style-{wait,seen,bg,work}, appended to the global
# window-status-style. No-op outside tmux.
#
# The whole body sits in one { … } block that ends in exit: bash parses it all
# before running any of it, so a watcher that runs for hours never reads a
# newer version of this file halfway through when the harness is updated.
{
set -uo pipefail

command -v tmux >/dev/null 2>&1 || exit 0
action=${1:-}
self=$(readlink -f "$0")

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
if [[ "$action" =~ ^(stop|notify|work|clear)$ && ! -t 0 ]]; then
  input=$(timeout 2 cat 2>/dev/null)
fi

field() {  # field <jq filter> <grep fallback pattern>
  if command -v jq >/dev/null 2>&1; then
    printf '%s' "$input" | jq -r "$1" 2>/dev/null
  else
    printf '%s' "$input" | grep -o "$2" | head -1
  fi
}

if [[ "$action" =~ ^(work|clear)$ && -n "$input" ]]; then
  [[ -n "$(field '.agent_id // empty' '"agent_id" *: *"[^"]')" ]] && exit 0
fi

claude_alive() {  # claude_alive <pid>: is that pid still a Claude process?
  [[ "$(ps -o comm= -p "$1" 2>/dev/null)" == claude ]]
}

claude_pid() {  # the Claude process this hook runs under
  local p=$PPID comm
  for _ in 1 2 3 4 5 6 7 8; do
    [[ -n "$p" && "$p" -gt 1 ]] || return 0
    comm=$(ps -o comm= -p "$p" 2>/dev/null)
    [[ "$comm" == claude ]] && { printf '%s' "$p"; return 0; }
    p=$(ps -o ppid= -p "$p" 2>/dev/null | tr -d ' ')
  done
}

# "pane:state[:pid]" entries of the target's window, for panes that still exist
# there and Claude processes that are still alive.
entries() {
  local panes e p rest s pid out=""
  panes=" $(tmux list-panes -t "$target" -F '#{pane_id}' 2>/dev/null | tr '\n' ' ') "
  for e in $(tmux show-options -wqv -t "$target" @claude_pending 2>/dev/null); do
    p=${e%%:*}; rest=${e#"$p"}; rest=${rest#:}
    s=${rest%%:*}; pid=""; [[ "$rest" == *:* ]] && pid=${rest#*:}
    [[ -n "$s" ]] || s="wait"             # an entry from before states existed
    [[ "$panes" == *" $p "* && " $out " != *" $p:"* ]] || continue
    [[ -z "$pid" ]] || claude_alive "$pid" || continue
    out="${out:+$out }$p:$s${pid:+:$pid}"
  done
  printf '%s' "$out"
}

without() {  # without <entries> <pane>
  local e out=""
  for e in $1; do [[ "${e%%:*}" == "$2" ]] || out="${out:+$out }$e"; done
  printf '%s' "$out"
}

state_of() {  # state_of <entries> <pane>
  local e rest
  for e in $1; do
    [[ "${e%%:*}" == "$2" ]] || continue
    rest=${e#*:}; printf '%s' "${rest%%:*}"; return
  done
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
      work) custom="fg=green" ;;
    esac
  fi
  base=$(tmux show-options -gwv window-status-style 2>/dev/null)
  printf '%s' "${base:+$base,}$custom"
}

apply() {  # apply <entries>: store them and paint the strongest state
  local best="" s e rest
  for s in wait seen bg work; do
    for e in $1; do
      rest=${e#*:}
      [[ "${rest%%:*}" == "$s" ]] && { best=$s; break 2; }
    done
  done
  if [[ -z "$best" ]]; then
    tmux set-option -wu -t "$target" @claude_pending 2>/dev/null
    tmux set-option -wu -t "$target" window-status-style 2>/dev/null
  else
    tmux set-option -w -t "$target" @claude_pending "$1" 2>/dev/null || return
    tmux set-option -w -t "$target" window-status-style "$(look "$best")" 2>/dev/null
  fi
}

mark() {  # mark <state>: record this pane's state (with its Claude pid)
  local rest pid
  pid=${CLAUDE_PID:-$(claude_pid)}
  rest=$(without "$(entries)" "$pane")
  apply "${rest:+$rest }$pane:$1${pid:+:$pid}"
}

register_seen_hook() {  # once per tmux server: visiting a window marks it seen
  local hook
  tmux show-hooks -g session-window-changed 2>/dev/null | grep -q 'tmux-pending' && return
  hook="run-shell -b 'bash \"$self\" seen #{window_id}'"
  tmux set-hook -g 'session-window-changed[71]' "$hook" 2>/dev/null
  tmux set-hook -g 'client-session-changed[71]' "$hook" 2>/dev/null
}

visible_now() {  # is the target window on screen for an attached client?
  [[ "$(tmux display-message -p -t "$target" '#{&&:#{window_active},#{session_attached}}' 2>/dev/null)" == 1 ]]
}

busy_on_screen() {  # does Claude Code's own screen say a turn is running?
  # While a turn runs (streaming, thinking, tools) the line just above the
  # prompt box is a spinner, "✻ Brewing… (12s · ↓ 3k tokens)"; a finished turn
  # leaves "✻ Brewed for 12s" and an interrupted one leaves nothing there. Some
  # modes also put "esc to interrupt" in the footer under the box. The prompt
  # box itself (between the last two rules) never counts, so typed text can't.
  local -a lines=() rules=()
  local i n top
  mapfile -t lines < <(tmux capture-pane -p -t "$pane" 2>/dev/null)
  (( ${#lines[@]} )) || return 1
  for (( i = ${#lines[@]} - 1, n = 0; i >= 0 && n < 3; i-- )); do
    [[ -n "${lines[i]//[[:space:]]/}" ]] || continue
    n=$((n + 1))
    [[ "${lines[i]}" == ────────* ]] && break
    [[ "${lines[i]}" == *'esc to interrupt'* ]] && return 0
  done
  for i in "${!lines[@]}"; do [[ "${lines[i]}" == ────────* ]] && rules+=("$i"); done
  (( ${#rules[@]} >= 2 )) || return 1
  top=${rules[${#rules[@]} - 2]}
  # The spinner sits in column 0 as "<glyph> <Verb>…", alone for the first
  # seconds and then "<glyph> <Verb>… (4s · …)", within the few lines above
  # the box (a tip or hint line may come between). Message lines start with
  # "●", "⎿" or indentation, so a reply that happens to end in "…" never counts.
  for (( i = top - 1, n = 0; i >= 0 && n < 4; i-- )); do
    [[ -n "${lines[i]//[[:space:]]/}" ]] || continue
    n=$((n + 1))
    if [[ "${lines[i]}" =~ ^([^[:space:]]+)\ [A-Z][A-Za-z-]*…(\ \(|[[:space:]]*$) ]]; then
      case "${BASH_REMATCH[1]}" in ●|⎿|❯|─*) ;; *) return 0 ;; esac
    fi
  done
  return 1
}

start_watch() {  # one watcher per pane while it has a mark
  local watcher pid detach=(nohup)
  watcher=$(tmux show-options -pqv -t "$pane" @claude_watch 2>/dev/null)
  if [[ -n "$watcher" ]] && kill -0 "$watcher" 2>/dev/null; then
    [[ -n "${TMUX_PENDING_DEBUG:-}" ]] && echo "$(date +%T) start_watch: $watcher already runs for $pane" >> "$TMUX_PENDING_DEBUG"
    return 0
  fi
  pid=${CLAUDE_PID:-$(claude_pid)}
  [[ -n "${TMUX_PENDING_DEBUG:-}" ]] && echo "$(date +%T) start_watch: pane=$pane claude=${pid:-none}" >> "$TMUX_PENDING_DEBUG"
  [[ -n "$pid" ]] || return 0
  command -v setsid >/dev/null 2>&1 && detach+=(setsid)   # not on macOS
  CLAUDE_PID=$pid TMUX_PANE=$pane "${detach[@]}" bash "$self" watch </dev/null >/dev/null 2>&1 &
  tmux set-option -p -t "$pane" @claude_watch "$!" 2>/dev/null
}

case "$action" in
  stop|notify|set)
    state="wait"
    current=$(entries)
    if [[ "$action" == stop ]]; then
      bg=$(field '(.background_tasks // []) | length' '"background_tasks" *: *\[ *{')
      [[ -n "$bg" && "$bg" != 0 ]] && state="bg"
    elif [[ "$action" == notify ]]; then
      # the 60-second idle reminder repeats a wait that is already marked; over
      # work it means the turn is over without a Stop, so it becomes wait
      mine=$(state_of "$current" "$pane")
      [[ "$(field '.notification_type // empty' 'idle_prompt')" == idle_prompt \
         && -n "$mine" && "$mine" != work ]] && exit 0
    fi
    [[ "$state" == wait ]] && visible_now && state="seen"
    register_seen_hook
    mark "$state"
    # a permission prompt: the watcher turns it back into work once it is granted
    [[ "$action" == notify ]] && start_watch
    ;;
  work)
    register_seen_hook
    mark work
    start_watch
    ;;
  clear)
    apply "$(without "$(entries)" "$pane")"
    ;;
  seen)
    current=$(entries)
    marked=""
    for e in $current; do
      rest=${e#*:}
      [[ "${rest%%:*}" == wait ]] && e="${e%%:*}:seen${rest#wait}"
      marked="${marked:+$marked }$e"
    done
    apply "$marked"
    # sweep every other marked window for Claude processes that died unannounced
    while read -r win marks; do
      [[ -n "$marks" && "$win" != "$target" ]] || continue
      target=$win; apply "$(entries)"
    done < <(tmux list-windows -a -F '#{window_id} #{@claude_pending}' 2>/dev/null)
    ;;
  watch)
    # work -> wait when the footer stops saying "esc to interrupt" (Esc, Ctrl+C:
    # no hook fires); wait -> work when it says so again (a granted permission,
    # whose PostToolUse only comes once the tool is done). Two polls in a row,
    # so a Stop hook racing the footer always wins. Never acts before it has
    # seen the footer once, in case a future UI words it differently.
    seen_busy=0 busy_n=0 idle_n=0 waiting_since=0 prev=""
    for _ in $(seq 21600); do                  # 12 hours at most
      sleep 2
      claude_alive "${CLAUDE_PID:-0}" || { apply "$(entries)"; break; }
      st=$(state_of "$(entries)" "$pane")
      # a hook changed the state since the last poll: count afresh, so the idle
      # spell before a new prompt's spinner appears is not held against it
      [[ "$st" == "$prev" ]] || { busy_n=0; idle_n=0; prev=$st; }
      if busy_on_screen; then seen_busy=1; busy_n=$((busy_n + 1)); idle_n=0; else idle_n=$((idle_n + 1)); busy_n=0; fi
      if [[ -n "${TMUX_PENDING_DEBUG:-}" ]]; then
        printf '%s pane=%s state=%s busy=%s idle=%s seen_busy=%s\n' "$(date +%T)" "$pane" "$st" "$busy_n" "$idle_n" "$seen_busy"
        tmux capture-pane -p -t "$pane" 2>&1 | grep -v '^[[:space:]]*$' | tail -12 | sed 's/^/    | /'
      fi >> "${TMUX_PENDING_DEBUG:-/dev/null}"
      case "$st" in
        work)
          waiting_since=0
          if (( seen_busy && idle_n >= 2 )); then
            state="wait"; visible_now && state="seen"
            mark "$state"
          fi ;;
        wait|seen)
          (( waiting_since )) || waiting_since=$SECONDS
          (( busy_n >= 2 )) && { mark work; continue; }
          (( SECONDS - waiting_since > 600 )) && break ;;   # nobody came back soon
        *) break ;;                                         # bg, cleared, gone
      esac
    done
    tmux set-option -pu -t "$pane" @claude_watch 2>/dev/null
    ;;
esac
exit 0
}
