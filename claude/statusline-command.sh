#!/usr/bin/env bash
# Claude Code statusLine — single-line catppuccin_mocha powerline
# Segments: user@host · cwd · git · model+flags+effort · ctx · 5h · 7d · time+edits
set -u
input=$(cat)

# ── palette (256-color, tmux-safe) ──────────────────────────────────
CRUST_FG=$'\033[38;5;232m'
LIGHT_FG=$'\033[38;5;255m'                 # cream-white text for dark sections
ACCENT_FG=$'\033[38;5;215m'                # gold (unused as fg now; kept for completeness)
# ── Palette (256-color, tmux-safe approximations) ───────────────────
# Section bg, dark navy → darker navy → teal → mint → beige → pale yellow
NAVY_BG=$'\033[48;5;17m'         NAVY_FG=$'\033[38;5;17m'         # ≈ #00005f  ≈ #1A3263
NAVY2_BG=$'\033[48;5;24m'        NAVY2_FG=$'\033[38;5;24m'        # ≈ #005f87  ≈ #205781
TEAL_HUE_BG=$'\033[48;5;73m'     TEAL_HUE_FG=$'\033[38;5;73m'     # ≈ #5fafaf  ≈ #4F959D
MINT_BG=$'\033[48;5;151m'        MINT_FG=$'\033[38;5;151m'        # ≈ #afd7af  ≈ #98D2C0
BEIGE_BG=$'\033[48;5;254m'       BEIGE_FG=$'\033[38;5;254m'       # ≈ #e4e4e4  ≈ #E5E1DA
PALEYEL_BG=$'\033[48;5;230m'     PALEYEL_FG=$'\033[38;5;230m'     # ≈ #ffffd7  ≈ #F6F8D5
GOLD_BG=$'\033[48;5;215m'        GOLD_FG=$'\033[38;5;215m'        # ≈ #ffaf5f  ≈ #FFC570 (POINT, bg only)
# Section assignments
RED_BG=$NAVY_BG          RED_FG=$NAVY_FG              # user@host
PEACH_BG=$NAVY2_BG       PEACH_FG=$NAVY2_FG           # cwd
YELLOW_BG=$TEAL_HUE_BG   YELLOW_FG=$TEAL_HUE_FG       # git branch
SAPPHIRE_BG=$MINT_BG     SAPPHIRE_FG=$MINT_FG         # model
GREEN_BG=$BEIGE_BG       GREEN_FG=$BEIGE_FG           # ctx / 5h / 7d grouped
TEAL_BG=$PALEYEL_BG      TEAL_FG=$PALEYEL_FG          # time + edits
# Gauge fills — filled = grade indicator, empty = section bg slightly darkened.
GAUGE_EMPTY_CTX=$'\033[48;5;250m'      # #bcbcbc ← darker than beige 254 for better contrast
GAUGE_EMPTY_MODEL=$'\033[48;5;108m'    # #87af87 ← slightly darker than mint 151
LOW_EMPTY_BG=$GAUGE_EMPTY_CTX     LOW_FILLED_BG=$'\033[48;5;109m'    # slate
MED_EMPTY_BG=$GAUGE_EMPTY_CTX     MED_FILLED_BG=$'\033[48;5;144m'    # dusty olive
HIGH_EMPTY_BG=$GAUGE_EMPTY_CTX    HIGH_FILLED_BG=$'\033[48;5;215m'   # gold POINT
GREEN_EMPTY_BG=$LOW_EMPTY_BG      GREEN_FILLED_BG=$LOW_FILLED_BG
YELLOW_EMPTY_BG=$MED_EMPTY_BG     YELLOW_FILLED_BG=$MED_FILLED_BG
RED_EMPTY_BG=$HIGH_EMPTY_BG       RED_FILLED_BG=$HIGH_FILLED_BG
SAPPHIRE_EMPTY_BG=$GAUGE_EMPTY_MODEL   SAPPHIRE_FILLED_BG=$'\033[48;5;67m'  # effort filled: navy
# Disabled-icon fg: medium gray; Active-icon fg: deep navy (#1A3263).
DIM_FG=$'\033[38;5;245m'
ON_FG=$NAVY_FG
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

# powerline segment helpers. Optional 4th/3rd arg overrides text fg (default CRUST).
seg_first() { local tfg="${3:-$CRUST_FG}"; printf '%s %s %s' "$1$tfg$BOLD" "$2" "$RESET"; }
seg()       { local tfg="${4:-$CRUST_FG}"; printf '%s%s%s%s%s %s %s' "$2" "$1" "$ARROW" "$RESET" "$1$tfg$BOLD" "$3" "$RESET"; }
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
    # fast — deep navy fg (active) vs gray fg (disabled); section bg unchanged
    if [ "$fast" = "true" ]; then
        c+="${ON_FG}󱐋${CRUST_FG}"
    else
        c+="${DIM_FG}󱐋${CRUST_FG}"
    fi
    c+="  "
    # thinking — same scheme
    if [ "$think" = "true" ]; then
        c+="${ON_FG}󰧑${CRUST_FG}"
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

# user@host (dark navy bg → light text)
l+=$(seg_first "$RED_BG" " ${user}@${host}" "$LIGHT_FG"); prev=$RED_FG

# cwd (mid navy bg → light text)
l+=$(seg "$PEACH_BG" "$prev" " ${cwd_short}" "$LIGHT_FG"); prev=$PEACH_FG

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
    g=$(gauge "$ctx_int" 7 "$GRADE_FILLED_BG" "$GRADE_EMPTY_BG")
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
