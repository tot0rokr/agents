#!/usr/bin/env bash
# UserPromptSubmit: stamp the prompt-arrival time into the model's context, and
# surface how long ago the previous answer ended. Also records the arrival time
# so the Stop hook can compute this turn's duration. State is per-session.
set -uo pipefail

input=$(cat)
sid=$(printf '%s' "$input" | jq -r '.session_id // "default"' 2>/dev/null || echo default)
[[ -z "$sid" || "$sid" == "null" ]] && sid=default

now_epoch=$(date +%s)
now_human=$(date '+%Y-%m-%d %H:%M:%S')

state_dir="$HOME/.claude/.timestamp-state"
mkdir -p "$state_dir"
printf '%s %s\n' "$now_epoch" "$now_human" > "$state_dir/${sid}.last-prompt"

line="⏱ 프롬프트 수신: ${now_human}"
end_file="$state_dir/${sid}.last-answer-end"
if [[ -f "$end_file" ]]; then
  read -r end_epoch end_human < "$end_file" || true
  if [[ -n "${end_epoch:-}" ]]; then
    gap=$(( now_epoch - end_epoch ))
    line="${line} · 직전 답변 종료 ${end_human} (${gap}s 전)"
  fi
fi

printf '%s\n' "$line"
