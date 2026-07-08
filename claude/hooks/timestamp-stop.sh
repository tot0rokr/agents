#!/usr/bin/env bash
# Stop: stamp the answer-end time (shown to the user as a systemMessage) and
# report how long this turn took, measured from the matching prompt arrival.
# The end time is recorded so the next prompt can report the idle gap. Per-session.
set -uo pipefail

input=$(cat)
sid=$(printf '%s' "$input" | jq -r '.session_id // "default"' 2>/dev/null || echo default)
[[ -z "$sid" || "$sid" == "null" ]] && sid=default

now_epoch=$(date +%s)
now_human=$(date '+%Y-%m-%d %H:%M:%S')

state_dir="$HOME/.claude/.timestamp-state"
mkdir -p "$state_dir"

msg="⏱ 답변 종료: ${now_human}"
threshold=180   # 이 초(3분) 이상 걸린 턴은 noti 웹훅으로 알림
prompt_file="$state_dir/${sid}.last-prompt"
if [[ -f "$prompt_file" ]]; then
  read -r start_epoch start_human < "$prompt_file" || true
  if [[ -n "${start_epoch:-}" ]]; then
    dur=$(( now_epoch - start_epoch ))
    msg="${msg} (소요 ${dur}s)"
    if (( dur >= threshold )) && command -v noti >/dev/null 2>&1; then
      # --- 카드에 채울 컨텍스트 수집 ---
      host=$(hostname -s 2>/dev/null || hostname 2>/dev/null || echo "${HOSTNAME:-unknown}")
      cwd=$(printf '%s' "$input" | jq -r '.cwd // empty' 2>/dev/null || true)
      [[ -z "$cwd" ]] && cwd="$PWD"
      transcript=$(printf '%s' "$input" | jq -r '.transcript_path // empty' 2>/dev/null || true)

      # 세션 이름: 사용자 지정 제목 > AI 생성 제목 > 세션 UUID 앞 8자리
      sname=""
      if [[ -n "$transcript" && -f "$transcript" ]]; then
        sname=$(jq -r 'select(.type=="custom-title") | .customTitle // empty' "$transcript" 2>/dev/null | tail -1)
        [[ -z "$sname" ]] && sname=$(jq -r 'select(.type=="ai-title") | .aiTitle // empty' "$transcript" 2>/dev/null | tail -1)
      fi
      [[ -z "$sname" ]] && sname="${sid:0:8}"

      # 마지막 사용자 프롬프트 앞부분. tool_result/시스템 리마인더/슬래시 커맨드는 제외하고,
      # jq 안에서 codepoint 단위로 잘라 한글이 반토막 나지 않게 한다.
      prompt=""
      if [[ -n "$transcript" && -f "$transcript" ]]; then
        prompt=$(jq -r --argjson max 180 '
          select(.type=="user" and (.message.content|type)=="string")
          | .message.content
          | select(test("^<(system-reminder|command|local-command|bash-|caveat)")|not)
          | gsub("\\s+"; " ") | gsub("^ +| +$"; "")
          | select(length > 0)
          | if length > $max then .[0:$max] + "…" else . end
        ' "$transcript" 2>/dev/null | tail -1)
      fi
      [[ -n "$prompt" ]] && desc="💬 ${prompt}" || desc="\`${cwd}\`"

      # 소요 시간 사람이 읽기 좋게 (Xh Ym Zs)
      if (( dur >= 3600 )); then
        dur_h="$(( dur/3600 ))h $(( (dur%3600)/60 ))m $(( dur%60 ))s"
      elif (( dur >= 60 )); then
        dur_h="$(( dur/60 ))m $(( dur%60 ))s"
      else
        dur_h="${dur}s"
      fi

      # 색상: 3~5분 골드, 5분+ 오렌지. 레드는 실패 알림 전용이라 완료 카드엔 안 씀.
      if (( dur >= 300 )); then color="0xE67E22"; else color="0xF1C40F"; fi

      # tmux 위치(있으면)
      tmux_info=""
      if [[ -n "${TMUX:-}" ]] && command -v tmux >/dev/null 2>&1; then
        tmux_info=$(tmux display-message -p '#S:#I.#P #W' 2>/dev/null || true)
      fi

      # 경로는 desc/필드 중복을 피해 여기 한 곳(작업 위치)에만 전체 경로로 넣는다.
      fields=(
        --field "⏱ 소요 시간" "$dur_h"
        --field "🖥 호스트"    "$host"
        --field "📁 작업 위치"  "$cwd"
        --field "🧵 세션"      "$sname"
      )
      [[ -n "$tmux_info" ]] && fields+=( --field "🪟 tmux" "$tmux_info" )

      nohup noti embed \
        --title "Claude 응답 완료" \
        --desc "$desc" \
        --color "$color" \
        "${fields[@]}" >/dev/null 2>&1 &
      msg="${msg} · 📨 noti 발송"
    fi
  fi
fi

printf '%s %s\n' "$now_epoch" "$now_human" > "$state_dir/${sid}.last-answer-end"

printf '{"systemMessage":%s,"suppressOutput":true}\n' "$(printf '%s' "$msg" | jq -Rs .)"
