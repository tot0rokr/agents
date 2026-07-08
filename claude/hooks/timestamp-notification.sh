#!/usr/bin/env bash
# Notification: Claude Code fires this when it wants the user's attention —
# a permission request ("Claude needs your permission …", "Claude wants to …"),
# a question / choice ("Claude needs your input"), or the plain idle wait
# ("Claude is waiting for your input") after a turn already finished.
#
# We alert on the attention-requests, not the plain idle wait, and we measure
# solely against the user's prompt-input time (never the answer-end time).
# A card goes out when ALL hold:
#   1) 실제 요청       — message 가 유휴 대기("… is waiting for your input")가 아님
#   2) 경과 >= 임계값   — 사용자 프롬프트 입력 이후 NOTI_CARD_THRESHOLD 초 이상
#   3) 이번 턴 첫 알림   — 프롬프트 입력 시각으로 dedupe, 반복 알림 도배 방지
set -uo pipefail

source "$HOME/.claude/hooks/lib/noti-card.sh"

input=$(cat)
sid=$(printf '%s' "$input" | jq -r '.session_id // "default"' 2>/dev/null || echo default)
[[ -z "$sid" || "$sid" == "null" ]] && sid=default

# 턴이 이미 끝난 뒤의 유휴 대기 알림은 완료 카드와 겹치므로 제외.
# 실제 요청(권한/질문)만 통과 — "needs your input"(질문)은 통과, "is waiting"(유휴)은 컷.
message=$(printf '%s' "$input" | jq -r '.message // empty' 2>/dev/null || true)
[[ "$message" == *"waiting for your input"* ]] && exit 0

state_dir="$HOME/.claude/.timestamp-state"
prompt_file="$state_dir/${sid}.last-prompt"
sent_file="$state_dir/${sid}.last-notify-card"

# 현재 턴의 프롬프트 입력 시각이 없으면 판단 불가 → 스킵.
[[ -f "$prompt_file" ]] || exit 0
read -r start_epoch _ < "$prompt_file" || true
[[ -n "${start_epoch:-}" ]] || exit 0

# 경과(프롬프트 입력 이후)가 임계값 미만이면 스킵.
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
