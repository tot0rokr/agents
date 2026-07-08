#!/usr/bin/env bash
# Notification: Claude Code fires this when it wants the user's attention —
# a permission prompt, a question/choice, or an idle "waiting for input".
# We only want the FIRST two: Claude ground away for a while and then paused
# mid-turn to ask. We send a noti "입력 대기" card when ALL hold:
#   1) 턴 진행 중        — .last-prompt 가 .last-answer-end 보다 최신
#                          (Stop 이 이미 찍혔으면 그냥 유휴 대기라 스킵)
#   2) 경과 >= 임계값     — 프롬프트 이후 NOTI_CARD_THRESHOLD 초 이상
#   3) 이번 턴 첫 알림    — 반복되는 유휴 알림으로 카드가 도배되지 않게
set -uo pipefail

source "$HOME/.claude/hooks/lib/noti-card.sh"

input=$(cat)
sid=$(printf '%s' "$input" | jq -r '.session_id // "default"' 2>/dev/null || echo default)
[[ -z "$sid" || "$sid" == "null" ]] && sid=default

state_dir="$HOME/.claude/.timestamp-state"
prompt_file="$state_dir/${sid}.last-prompt"
end_file="$state_dir/${sid}.last-answer-end"
sent_file="$state_dir/${sid}.last-notify-card"

# 현재 턴 시작 시각이 없으면 판단 불가 → 스킵.
[[ -f "$prompt_file" ]] || exit 0
read -r start_epoch _ < "$prompt_file" || true
[[ -n "${start_epoch:-}" ]] || exit 0

# 직전 답변 종료 시각. 프롬프트보다 최신이면 턴이 이미 끝난 상태(유휴 대기) → 스킵.
end_epoch=0
if [[ -f "$end_file" ]]; then read -r end_epoch _ < "$end_file" || true; fi
(( start_epoch > ${end_epoch:-0} )) || exit 0

# 경과가 임계값 미만이면 스킵.
now_epoch=$(date +%s)
elapsed=$(( now_epoch - start_epoch ))
(( elapsed >= NOTI_CARD_THRESHOLD )) || exit 0

# 이번 턴에 이미 알림 카드를 보냈으면 스킵(턴당 1회).
last_sent=""
if [[ -f "$sent_file" ]]; then read -r last_sent _ < "$sent_file" || true; fi
[[ "${last_sent:-}" == "$start_epoch" ]] && exit 0

mkdir -p "$state_dir"
printf '%s\n' "$start_epoch" > "$sent_file"   # 발송 전에 먼저 표시해 중복 방지
emit_noti_card "$input" "$elapsed" notify
exit 0
