#!/usr/bin/env bash
# Stop: stamp the answer-end time (shown to the user as a systemMessage) and
# report how long this turn took, measured from the matching prompt arrival.
# The end time is recorded so the next prompt can report the idle gap. Per-session.
# On long turns (>= threshold) also fire a noti "완료" card. See lib/noti-card.sh.
set -uo pipefail

source "$HOME/.claude/hooks/lib/noti-card.sh"

input=$(cat)
sid=$(printf '%s' "$input" | jq -r '.session_id // "default"' 2>/dev/null || echo default)
[[ -z "$sid" || "$sid" == "null" ]] && sid=default

now_epoch=$(date +%s)
now_human=$(date '+%Y-%m-%d %H:%M:%S')

state_dir="$HOME/.claude/.timestamp-state"
mkdir -p "$state_dir"

msg="⏱ 답변 종료: ${now_human}"
prompt_file="$state_dir/${sid}.last-prompt"
if [[ -f "$prompt_file" ]]; then
  read -r start_epoch start_human < "$prompt_file" || true
  if [[ -n "${start_epoch:-}" ]]; then
    dur=$(( now_epoch - start_epoch ))
    msg="${msg} (소요 ${dur}s)"
    if (( dur >= NOTI_CARD_THRESHOLD )) && command -v noti >/dev/null 2>&1; then
      emit_noti_card "$input" "$dur" stop
      msg="${msg} · 📨 noti 발송"
    fi
  fi
fi

printf '%s %s\n' "$now_epoch" "$now_human" > "$state_dir/${sid}.last-answer-end"

printf '{"systemMessage":%s,"suppressOutput":true}\n' "$(printf '%s' "$msg" | jq -Rs .)"
