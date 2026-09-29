#!/usr/bin/env bash
# fork-session.sh — fork a running Claude Code session into a new tmux window.
#
# The fork is a native `claude --resume <id> --fork-session`: a new session id
# that carries the whole conversation so far, while the original keeps running
# untouched — so you can ask it things mid-task. The fork is started the way the
# original was (same wrapper such as claude-auto, same --plugin-dir/--settings/…
# flags, same working directory) and opens right next to the original's window.
#
# usage: fork-session.sh [--pane %N | --session ID] [--split] [--tag TAG | --name NAME] [--dry-run]
#   (no source)   the session this runs in ($CLAUDE_CODE_SESSION_ID), for the skill
#   --pane %N     the Claude session running in that tmux pane, for a key binding:
#                 bind-key F run-shell "bash ~/.claude/skills/fork-session/fork-session.sh --pane '#{pane_id}'"
#   --session ID  that session id
#   --split       a pane beside the original instead of a new window
#   --tag TAG     name the fork "<base>#TAG" instead of the next "<base>#N"
#   --name NAME   the fork's whole name, as given
#   --dry-run     print what would run, start nothing
#
# Names: <base>#1, <base>#2, … where <base> is the original's name (Claude Code
# names sessions "<folder>-<2 chars>"; a nameless one gets exactly that from its
# folder and session id). Forking a fork counts on from the same base instead
# of stacking suffixes. The tmux window gets the same name.
set -uo pipefail

die() { echo "fork-session: $*" >&2; exit 1; }
command -v jq >/dev/null 2>&1 || die "needs jq"

pane="" sid="${CLAUDE_CODE_SESSION_ID:-}" split=0 name="" tag="" dry=0
while (( $# )); do
  case "$1" in
    --pane) pane=${2:-}; sid=""; shift 2 ;;
    --session) sid=${2:-}; pane=""; shift 2 ;;
    --split) split=1; shift ;;
    --tag) tag=${2:-}; shift 2 ;;
    --name) name=${2:-}; shift 2 ;;
    --dry-run) dry=1; shift ;;
    -h|--help) sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown argument: $1 (see --help)" ;;
  esac
done
[[ -n "$pane$sid" ]] || die "no session to fork: run inside Claude Code, or pass --pane / --session"

# --- the source session, from Claude Code's live-session registry --------------
registry="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/sessions"

under() {  # under <pid> <ancestor pid>: is pid a descendant of ancestor?
  local p=$1
  for _ in 1 2 3 4 5 6 7 8; do
    [[ "$p" == "$2" ]] && return 0
    p=$(ps -o ppid= -p "$p" 2>/dev/null | tr -d ' ')
    [[ -n "$p" && "$p" -gt 1 ]] || return 1
  done
  return 1
}

in_pane() {  # in_pane <pane id>: the registry file of the Claude running in it
  # By process ancestry, not the registry's "tmux" field: that one names the
  # session, window and pane but not the tmux server, so it can be ambiguous.
  local ppid f
  ppid=$(tmux display-message -p -t "$1" '#{pane_pid}' 2>/dev/null) || return 1
  for f in "$registry"/*.json; do
    [[ -f "$f" ]] || continue
    kill -0 "$(basename "$f" .json)" 2>/dev/null || continue   # it keeps dead ones too
    under "$(basename "$f" .json)" "$ppid" && { printf '%s' "$f"; return 0; }
  done
  return 1
}

file=""
if [[ -n "$pane" ]]; then
  file=$(in_pane "$pane")
else
  for f in "$registry"/*.json; do
    [[ -f "$f" ]] || continue
    kill -0 "$(basename "$f" .json)" 2>/dev/null || continue
    jq -e --arg s "$sid" '.sessionId == $s' "$f" >/dev/null 2>&1 && { file=$f; break; }
  done
fi
[[ -n "$file" ]] || die "no running Claude session found for ${pane:+pane $pane}${sid:+session $sid}"
entry=$(cat "$file")
src_pid=$(jq -r .pid <<<"$entry")
src_sid=$(jq -r .sessionId <<<"$entry")
cwd=$(jq -r '.cwd // empty' <<<"$entry")
src_name=$(jq -r '.name // empty' <<<"$entry")
if [[ -n "$pane" ]]; then src_pane=$pane
elif [[ "$src_sid" == "${CLAUDE_CODE_SESSION_ID:-}" && -n "${TMUX_PANE:-}" ]]; then src_pane=$TMUX_PANE
else src_pane=$(jq -r '(.tmux // "") | sub("^.*\\."; "")' <<<"$entry"); fi
[[ -d "$cwd" ]] || die "the session's directory is gone: $cwd"

# --- how the original was started -------------------------------------------------
argv_of() { tr '\0' '\n' < "/proc/$1/cmdline" 2>/dev/null; }
mapfile -t src_argv < <(argv_of "$src_pid")
launcher=()
if (( ${#src_argv[@]} )); then
  launcher=("${src_argv[0]}")
  # a wrapper script such as claude-auto: "bash /path/claude-auto <same args>"
  ppid=$(ps -o ppid= -p "$src_pid" 2>/dev/null | tr -d ' ')
  mapfile -t parent_argv < <(argv_of "${ppid:-0}")
  if (( ${#parent_argv[@]} >= 2 )) && [[ "$(basename "${parent_argv[0]}")" =~ ^(ba|z|da)?sh$ \
        && "$(basename "${parent_argv[1]}")" == claude* && -f "${parent_argv[1]}" ]]; then
    launcher=("${parent_argv[1]}")
  fi
else
  launcher=(claude)                                  # no /proc (macOS): plain claude
fi

# Only flags that describe the environment carry over; a prompt argument, -p,
# --resume/--continue/--session-id and anything unknown do not.
carry=()
takes_value=" --plugin-dir --add-dir --model --permission-mode --settings --mcp-config --agent --append-system-prompt "
standalone=" --dangerously-skip-permissions --strict-mcp-config "
for (( i = 1; i < ${#src_argv[@]}; i++ )); do
  a=${src_argv[i]}
  if [[ "$a" == --*=* && "$takes_value" == *" ${a%%=*} "* ]]; then carry+=("$a")
  elif [[ "$takes_value" == *" $a "* ]]; then carry+=("$a" "${src_argv[i+1]:-}"); i=$((i + 1))
  elif [[ "$standalone" == *" $a "* ]]; then carry+=("$a")
  fi
done

# --- the fork's name ---------------------------------------------------------------
base=${src_name:-$(basename "$cwd")-${src_sid:0:2}}
# the original is itself a fork: count on from its base ("x#2" -> "x"), but leave
# alone a name the user happened to write with a "#" in it
[[ " ${src_argv[*]} " == *" --fork-session "* && "$base" == *"#"* ]] && base=${base%#*}
if [[ -n "$name" ]]; then fork_name=$name
elif [[ -n "$tag" ]]; then fork_name="$base#${tag//[[:space:]#]/-}"
else
  # next free number among every session the registry has seen with this base
  n=0
  while read -r used; do
    [[ "$used" =~ ^[0-9]+$ ]] && (( used > n )) && n=$used
  done < <(jq -r --arg b "$base#" '(.name // "") | select(startswith($b)) | ltrimstr($b)' "$registry"/*.json 2>/dev/null)
  fork_name="$base#$((n + 1))"
fi
cmd=("${launcher[@]}" "${carry[@]}" --resume "$src_sid" --fork-session --name "$fork_name")

# If the fork dies at once (say the session cannot be resumed), keep the window
# open long enough to read why instead of letting it vanish.
q=$(printf '%q ' "${cmd[@]}")
shell_cmd="cd $(printf %q "$cwd") && $q; rc=\$?; [ \$rc -eq 0 ] || { echo; echo \"fork-session: claude exited with \$rc\"; read -r -p 'press Enter to close ' _; }"

if (( dry )) || [[ -z "${TMUX:-}" ]] || ! command -v tmux >/dev/null 2>&1; then
  (( dry )) || echo "fork-session: not inside tmux — run this in a new terminal:" >&2
  printf 'cd %q && %s\n' "$cwd" "$q"
  exit 0
fi

# --- open it next to the original -----------------------------------------------
target=${src_pane:-${TMUX_PANE:-}}
if (( split )); then
  new_pane=$(tmux split-window -h -P -F '#{pane_id}' ${target:+-t "$target"} -c "$cwd" "$shell_cmd") \
    || die "tmux split-window failed"
else
  # new-window takes a window, not a pane, as its target
  win=${target:+$(tmux display-message -p -t "$target" '#{window_id}' 2>/dev/null)}
  # tmux expands formats in -n ("#S" would become the session name): double the #
  new_pane=$(tmux new-window -a -P -F '#{pane_id}' ${win:+-t "$win"} -n "${fork_name//#/##}" -c "$cwd" "$shell_cmd") \
    || die "tmux new-window failed"
fi

# The fork registers itself once it is up; report its session id.
new_sid=""
for _ in $(seq 40); do
  sleep 0.5
  f=$(in_pane "$new_pane") && { new_sid=$(jq -r .sessionId "$f"); break; }
done
echo "forked $src_sid (${src_name:-unnamed}, pane $src_pane)"
echo "  -> $(tmux display-message -p -t "$new_pane" '#{session_name}:#{window_index} (#{window_name})' 2>/dev/null) pane $new_pane, session ${new_sid:-starting…}, name $fork_name"
