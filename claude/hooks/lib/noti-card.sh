#!/usr/bin/env bash
# Shared helper for the timestamp hooks: build and send a noti embed "card"
# describing a turn event. Sourced by timestamp-stop.sh (turn finished) and
# timestamp-notification.sh (Claude paused mid-turn to ask the user).
#
# Colors are chosen so the three states never collide at a glance:
#   완료(짧음) 골드 / 완료(김) 오렌지 / 입력 대기 블루 / 실패 레드(다른 도구 전용)

# 이 초(3분) 이상 걸린 뒤의 이벤트에만 카드를 보낸다. 두 훅이 공유한다.
: "${NOTI_CARD_THRESHOLD:=180}"

# 세션 표시 이름: 사용자 지정 제목 > AI 생성 제목 > 세션 UUID 앞 8자리
noti_session_name() {
  local transcript="$1" sid="$2" sname=""
  if [[ -n "$transcript" && -f "$transcript" ]]; then
    sname=$(jq -r 'select(.type=="custom-title") | .customTitle // empty' "$transcript" 2>/dev/null | tail -1)
    [[ -z "$sname" ]] && sname=$(jq -r 'select(.type=="ai-title") | .aiTitle // empty' "$transcript" 2>/dev/null | tail -1)
  fi
  [[ -z "$sname" ]] && sname="${sid:0:8}"
  printf '%s' "$sname"
}

# 마지막 사용자 프롬프트 앞부분. tool_result/시스템 리마인더/슬래시 커맨드는 제외하고,
# jq 안에서 codepoint 단위로 잘라 한글이 반토막 나지 않게 한다.
noti_last_prompt() {
  local transcript="$1" max="${2:-180}"
  [[ -n "$transcript" && -f "$transcript" ]] || return 0
  jq -r --argjson max "$max" '
    select(.type=="user" and (.message.content|type)=="string")
    | .message.content
    | select(test("^<(system-reminder|command|local-command|bash-|caveat)")|not)
    | gsub("\\s+"; " ") | gsub("^ +| +$"; "")
    | select(length > 0)
    | if length > $max then .[0:$max] + "…" else . end
  ' "$transcript" 2>/dev/null | tail -1
}

# 소요 시간을 사람이 읽기 좋게 (Xh Ym Zs)
noti_fmt_dur() {
  local d="$1"
  if   (( d >= 3600 )); then printf '%dh %dm %ds' $((d/3600)) $(((d%3600)/60)) $((d%60))
  elif (( d >= 60 ));   then printf '%dm %ds' $((d/60)) $((d%60))
  else printf '%ds' "$d"; fi
}

# tmux 위치 (tmux 안이 아니면 빈 문자열)
noti_tmux() {
  { [[ -n "${TMUX:-}" ]] && command -v tmux >/dev/null 2>&1; } || return 0
  tmux display-message -p '#S:#I.#P #W' 2>/dev/null || true
}

# 카드 발송.  $1 훅 입력 JSON,  $2 소요/경과 초,  $3 종류(stop|notify)
emit_noti_card() {
  local input="$1" dur="$2" kind="$3"
  command -v noti >/dev/null 2>&1 || return 0

  local sid host cwd transcript sname tmux_info title color desc dur_label
  sid=$(printf '%s' "$input" | jq -r '.session_id // "default"' 2>/dev/null || echo default)
  host=$(hostname -s 2>/dev/null || hostname 2>/dev/null || echo "${HOSTNAME:-unknown}")
  cwd=$(printf '%s' "$input" | jq -r '.cwd // empty' 2>/dev/null || true); [[ -z "$cwd" ]] && cwd="$PWD"
  transcript=$(printf '%s' "$input" | jq -r '.transcript_path // empty' 2>/dev/null || true)
  sname=$(noti_session_name "$transcript" "$sid")
  tmux_info=$(noti_tmux)
  dur_label="⏱ 소요 시간"

  if [[ "$kind" == notify ]]; then
    # 턴 진행 중 사용자에게 되물음 — 파랑, 무엇을 묻는지 desc에.
    local message
    message=$(printf '%s' "$input" | jq -r '.message // empty' 2>/dev/null || true)
    title="⏸ Claude 입력 대기"
    dur_label="⏱ 경과 시간"
    desc="❓ ${message:-사용자 입력을 기다립니다}"
    color="0x3498DB"
  else
    # 턴 완료 — 3~5분 골드, 5분+ 오렌지. desc는 마지막 프롬프트 앞부분.
    local prompt
    prompt=$(noti_last_prompt "$transcript")
    [[ -n "$prompt" ]] && desc="💬 ${prompt}" || desc="\`${cwd}\`"
    if (( dur >= 300 )); then color="0xE67E22"; else color="0xF1C40F"; fi
    title="Claude 응답 완료"
  fi

  # 경로는 desc/필드 중복을 피해 작업 위치 필드 한 곳에만 전체 경로로.
  local fields=(
    --field "$dur_label"   "$(noti_fmt_dur "$dur")"
    --field "🖥 호스트"     "$host"
    --field "📁 작업 위치"   "$cwd"
    --field "🧵 세션"       "$sname"
  )
  [[ -n "$tmux_info" ]] && fields+=( --field "🪟 tmux" "$tmux_info" )

  nohup noti embed --title "$title" --desc "$desc" --color "$color" "${fields[@]}" >/dev/null 2>&1 &
}
