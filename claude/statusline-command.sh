#!/usr/bin/env bash
# Claude Code statusLine — single-line catppuccin_mocha powerline
# Segments: user@host · cwd · git · model+flags+effort · ctx · 5h · 7d · time+edits
set -u
input=$(cat)

# ── palette (256-color, tmux-safe) ──────────────────────────────────
CRUST_FG=$'\033[38;5;232m'
RED_BG=$'\033[48;5;211m'      RED_FG=$'\033[38;5;211m'
PEACH_BG=$'\033[48;5;216m'    PEACH_FG=$'\033[38;5;216m'
YELLOW_BG=$'\033[48;5;222m'   YELLOW_FG=$'\033[38;5;222m'
GREEN_BG=$'\033[48;5;151m'    GREEN_FG=$'\033[38;5;151m'
TEAL_BG=$'\033[48;5;116m'     TEAL_FG=$'\033[38;5;116m'
SAPPHIRE_BG=$'\033[48;5;117m' SAPPHIRE_FG=$'\033[38;5;117m'
# Per-segment 2-tone gauge fills: empty (slightly darker than section), filled (more darker).
GREEN_EMPTY_BG=$'\033[48;5;108m'      # #87af87 sage
GREEN_FILLED_BG=$'\033[48;5;65m'      # #5f875f forest
YELLOW_EMPTY_BG=$'\033[48;5;178m'     # #d7af00 gold
YELLOW_FILLED_BG=$'\033[48;5;136m'    # #af8700 dark gold
RED_EMPTY_BG=$'\033[48;5;174m'        # #d78787 salmon
RED_FILLED_BG=$'\033[48;5;131m'       # #af5f5f rose brown
SAPPHIRE_EMPTY_BG=$'\033[48;5;74m'    # #5fafd7 sky
SAPPHIRE_FILLED_BG=$'\033[48;5;67m'   # #5f87af slate
# Muted fg for "disabled" icons on sapphire bg (same hue, darker).
DIM_FG=$'\033[38;5;67m'
RESET=$'\033[0m'
BOLD=$'\033[1m'
DIM=$'\033[2m'
UNDIM=$'\033[22m'   # resets bold+dim → re-apply BOLD after this
ARROW=$''     # powerline solid right triangle
ICON_USER=$''        # person
ICON_FOLDER=$''      # folder
ICON_BRANCH=$''      # git branch
ICON_MODEL=$'9'      # md-robot
ICON_FAST_ON=$'b'    # md-lightning-bolt (filled)
ICON_FAST_OFF=$'c'   # md-lightning-bolt-outline
ICON_THINK=$'1'      # md-head-cog
ICON_GAUGE=$'5'      # md-speedometer
ICON_CTX=$'b'        # md-memory
ICON_5H=$'b'         # md-timer-sand
ICON_7D=$'d'         # md-calendar
ICON_CLOCK=$''       # md-clock (starship-match)
ICON_EDIT=$'8'       # md-file-edit

# ── helpers ─────────────────────────────────────────────────────────
shorten_path() {
    local p="$1" max=3 IFS=/
    read -ra parts <<<"$p"
    local n=${#parts[@]}
    if [ "$n" -le "$max" ]; then printf '%s' "$p"; return; fi
    local i s='…'
    for ((i = n - max; i < n; i++)); do s+="/${parts[i]}"; done
    printf '%s' "$s"
}

bar_n() {
    local pct="$1" w="$2" filled i b=''
    filled=$((pct * w / 100))
    [ "$filled" -gt "$w" ] && filled=$w
    for ((i = 0; i < w; i++)); do
        if [ "$i" -lt "$filled" ]; then b+='▓'; else b+='░'; fi
    done
    printf '%s' "$b"
}

# Bg-colored gauge with text overlay. Filled+empty are darker shades of the
# section bg (same hue, two intensities); fg is CRUST throughout.
#   args: pct, width, filled_bg, empty_bg
gauge() {
    local pct="$1" w="$2" FBG="$3" EBG="$4"
    local txt="${pct}%"
    local tlen=${#txt}
    local start=$(( (w - tlen) / 2 ))
    local end=$((start + tlen))
    local filled=$((pct * w / 100))
    [ "$filled" -gt "$w" ] && filled=$w
    local out='' i bg ch
    for ((i = 0; i < w; i++)); do
        if [ "$i" -lt "$filled" ]; then bg=$FBG
        else                            bg=$EBG
        fi
        if [ "$i" -ge "$start" ] && [ "$i" -lt "$end" ]; then
            ch="${txt:$((i - start)):1}"
        else
            ch=' '
        fi
        out+="${bg}${CRUST_FG}${ch}"
    done
    printf '%s' "$out"
}

# Section bg/fg always stay green (neutral container); only gauge fill colors
# (GRADE_EMPTY_BG / GRADE_FILLED_BG) vary by percentage so the warning shows
# inside the gauge instead of flooding the whole segment.
grade() {
    local p="$1"
    GRADE_BG=$GREEN_BG
    GRADE_FG=$GREEN_FG
    if   [ "$p" -lt 60 ]; then
        GRADE_EMPTY_BG=$GREEN_EMPTY_BG;  GRADE_FILLED_BG=$GREEN_FILLED_BG
    elif [ "$p" -lt 85 ]; then
        GRADE_EMPTY_BG=$YELLOW_EMPTY_BG; GRADE_FILLED_BG=$YELLOW_FILLED_BG
    else
        GRADE_EMPTY_BG=$RED_EMPTY_BG;    GRADE_FILLED_BG=$RED_FILLED_BG
    fi
}

# Effort gauge: 5-cell bg-colored bar with L/M/H/X letter at center.
# Uses sapphire's filled/empty pair (darker shades of section).
effort_gauge() {
    local lvl="$1" letter level w=5 center=2
    case "$lvl" in
        low)    letter='L'; level=1 ;;
        medium) letter='M'; level=2 ;;
        high)   letter='H'; level=3 ;;
        xhigh)  letter='X'; level=4 ;;
        *)      letter='?'; level=0 ;;
    esac
    local filled=$((level * w / 4))
    [ "$filled" -gt "$w" ] && filled=$w
    local out='' i bg ch
    for ((i = 0; i < w; i++)); do
        if [ "$i" -lt "$filled" ]; then bg=$SAPPHIRE_FILLED_BG
        else                            bg=$SAPPHIRE_EMPTY_BG
        fi
        if [ "$i" -eq "$center" ]; then ch="$letter"
        else                             ch=' '
        fi
        out+="${bg}${CRUST_FG}${ch}"
    done
    printf '%s' "$out"
}

fmt_dur() {
    local ms="$1"
    local s=$((ms / 1000))
    if   [ "$s" -lt 60 ];   then printf '%ds' "$s"
    elif [ "$s" -lt 3600 ]; then printf '%dm' "$((s / 60))"
    else                         printf '%dh%dm' "$((s / 3600))" "$(((s % 3600) / 60))"
    fi
}

# powerline segment helpers
seg_first() { printf '%s %s %s' "$1$CRUST_FG$BOLD" "$2" "$RESET"; }
seg()       { printf '%s%s%s%s%s %s %s' "$2" "$1" "$ARROW" "$RESET" "$1$CRUST_FG$BOLD" "$3" "$RESET"; }
seg_close() { printf '%s%s%s' "$1" "$ARROW" "$RESET"; }

# ── data extraction ─────────────────────────────────────────────────
user=$(whoami)
host=$(hostname -s)
cwd=$(jq -r '.workspace.current_dir // .cwd // empty' <<<"$input")
[ -z "$cwd" ] && cwd=$(pwd)

branch=""
if b=$(git -C "$cwd" symbolic-ref --short HEAD 2>/dev/null); then branch="$b"
elif sha=$(git -C "$cwd" rev-parse --short HEAD 2>/dev/null); then branch="$sha"
fi

case "$cwd" in
    "$HOME") cwd='~' ;;
    "$HOME"/*) cwd="~${cwd#"$HOME"}" ;;
esac
cwd_short=$(shorten_path "$cwd")

model=$(jq -r '.model.display_name // empty' <<<"$input")
fast=$(jq -r '.fast_mode // false' <<<"$input")
think=$(jq -r '.thinking.enabled // false' <<<"$input")
effort=$(jq -r '.effort.level // empty' <<<"$input")

ctx_pct=$(jq -r '.context_window.used_percentage // empty' <<<"$input")
ctx_int=""; [ -n "$ctx_pct" ] && ctx_int=$(printf '%.0f' "$ctx_pct")

r5=$(jq -r '.rate_limits.five_hour.used_percentage // empty' <<<"$input")
r7=$(jq -r '.rate_limits.seven_day.used_percentage // empty' <<<"$input")
r5_int=""; [ -n "$r5" ] && r5_int=$(printf '%.0f' "$r5")
r7_int=""; [ -n "$r7" ] && r7_int=$(printf '%.0f' "$r7")

dur=$(jq -r '.cost.total_duration_ms // empty' <<<"$input")
ladd=$(jq -r '.cost.total_lines_added // 0' <<<"$input")
lrem=$(jq -r '.cost.total_lines_removed // 0' <<<"$input")

# ── model segment content: model · ⚡flag · 󰧑flag · 󰓅gauge ──────────
build_model_content() {
    local c="󰚩 ${model}  "
    # fast — always filled bolt; fg color shows on/off
    if [ "$fast" = "true" ]; then
        c+="󱐋"
    else
        c+="${DIM_FG}󱐋${CRUST_FG}"
    fi
    c+="  "
    # thinking — same glyph; fg color shows on/off
    if [ "$think" = "true" ]; then
        c+="󰧑"
    else
        c+="${DIM_FG}󰧑${CRUST_FG}"
    fi
    c+="  "
    # effort gauge — 5-cell bg-colored, letter inside
    c+="󰓅 $(effort_gauge "$effort")"
    # restore segment styling for any trailing chars
    c+="${SAPPHIRE_BG}${CRUST_FG}${BOLD}"
    printf '%s' "$c"
}

# ── compose powerline ───────────────────────────────────────────────
l=""; prev=""

# user@host
l+=$(seg_first "$RED_BG" " ${user}@${host}"); prev=$RED_FG

# cwd
l+=$(seg "$PEACH_BG" "$prev" " ${cwd_short}"); prev=$PEACH_FG

# git branch (optional)
if [ -n "$branch" ]; then
    l+=$(seg "$YELLOW_BG" "$prev" " ${branch}"); prev=$YELLOW_FG
fi

# model + flags + effort
if [ -n "$model" ]; then
    l+=$(seg "$SAPPHIRE_BG" "$prev" "$(build_model_content)"); prev=$SAPPHIRE_FG
fi

# ctx · 5h · 7d — all "grade" segments grouped without arrows between them.
# Only the first one gets a leading arrow (from the previous non-grade segment).
prev_was_grade=false

# ctx
if [ -n "$ctx_int" ]; then
    grade "$ctx_int"
    g=$(gauge "$ctx_int" 9 "$GRADE_FILLED_BG" "$GRADE_EMPTY_BG")
    content="󰍛 ${g}${GRADE_BG}${CRUST_FG}${BOLD}"
    l+=$(seg "$GRADE_BG" "$prev" "$content"); prev=$GRADE_FG
    prev_was_grade=true
fi

# 5h limit
if [ -n "$r5_int" ]; then
    grade "$r5_int"
    g=$(gauge "$r5_int" 7 "$GRADE_FILLED_BG" "$GRADE_EMPTY_BG")
    content="󰔛 ${g}${GRADE_BG}${CRUST_FG}${BOLD}"
    if $prev_was_grade; then
        l+=$(seg_first "$GRADE_BG" "$content")
    else
        l+=$(seg "$GRADE_BG" "$prev" "$content")
    fi
    prev=$GRADE_FG
    prev_was_grade=true
fi

# 7d limit
if [ -n "$r7_int" ]; then
    grade "$r7_int"
    g=$(gauge "$r7_int" 7 "$GRADE_FILLED_BG" "$GRADE_EMPTY_BG")
    content="󰃭 ${g}${GRADE_BG}${CRUST_FG}${BOLD}"
    if $prev_was_grade; then
        l+=$(seg_first "$GRADE_BG" "$content")
    else
        l+=$(seg "$GRADE_BG" "$prev" "$content")
    fi
    prev=$GRADE_FG
    prev_was_grade=true
fi

# duration + edits (teal)
dur_str=""
edit_str=""
if [ -n "$dur" ] && [ "$dur" -gt 0 ]; then
    dur_str="${ICON_CLOCK} $(fmt_dur "$dur")"
fi
if [ "$ladd" -gt 0 ] || [ "$lrem" -gt 0 ]; then
    edit_str="󰷈 +${ladd} -${lrem}"
fi
extras=""
if [ -n "$dur_str" ] && [ -n "$edit_str" ]; then
    extras="${dur_str}  ${edit_str}"
else
    extras="${dur_str}${edit_str}"
fi
if [ -n "$extras" ]; then
    l+=$(seg "$TEAL_BG" "$prev" "$extras"); prev=$TEAL_FG
fi

l+=$(seg_close "$prev")
printf '%s' "$l"
