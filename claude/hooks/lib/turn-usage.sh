#!/usr/bin/env bash
# Shared helper for timestamp-stop.sh: sum one turn's token usage from the
# session transcript and estimate what it costs at API list prices.
#
# A turn is whatever was appended to the transcript after the byte offset
# recorded at prompt arrival, plus the subagent transcripts written since then.
# The hook input carries no cost, so the amount is an estimate, not a bill.

# Prices are USD per million tokens. Cache writes cost 1.25x input (5-minute
# TTL) or 2x input (1-hour TTL); fast mode doubles the whole request.
# Source: https://platform.claude.com/docs/en/about-claude/pricing
#
# One API response is logged once per content block with the same usage, so
# entries are keyed by message id.
TURN_USAGE_JQ='
def prices: {
  "claude-fable-5-2":  {in: 8,   out: 40,  cache_read: 0.20},
  "claude-opus-5-5":   {in: 4,   out: 20,  cache_read: 0.20},
  "claude-sonnet-5-5": {in: 2,   out: 10,  cache_read: 0.10},
  "claude-haiku-5-5":  {in: 0.1, out: 0.5, cache_read: 0.01}
};
def compact:
  if . >= 1000000 then "\(. / 10000 | round / 100)M"
  elif . >= 1000 then "\(. / 100 | round / 10)k"
  else tostring end;

reduce (
  inputs | fromjson?
  | select(.type == "assistant" and (.message.usage | type) == "object")
  | select(.message.model != "<synthetic>")
  | select(((.timestamp // "")[0:19] + "Z" | try fromdateiso8601 catch 0) >= $start)
  | .message
) as $m ({}; .[$m.id] = {model: $m.model, usage: $m.usage})
| [.[] | .usage as $u | prices[.model] as $p
   | ($u.cache_creation_input_tokens // 0) as $write
   | ($u.cache_creation.ephemeral_1h_input_tokens // 0) as $write_1h
   | {
       model,
       uncached: ($u.input_tokens // 0),
       cache_read: ($u.cache_read_input_tokens // 0),
       cache_write: $write,
       out: ($u.output_tokens // 0),
       cost: (if $p == null then null else
         ( ($u.input_tokens // 0) * $p.in
         + ($write - $write_1h) * $p.in * 1.25
         + $write_1h * $p.in * 2
         + ($u.cache_read_input_tokens // 0) * $p.cache_read
         + ($u.output_tokens // 0) * $p.out
         ) / 1000000 * (if $u.speed == "fast" then 2 else 1 end)
       end)
     }]
| select(length > 0)
| [
    (map(.uncached + .cache_read + .cache_write) | add | compact),
    (map(.uncached) | add | compact),
    (map(.cache_read) | add | compact),
    (map(.cache_write) | add | compact),
    (map(.out) | add | compact),
    (map(.cost // 0) | add),
    (map(select(.cost == null) | .model) | unique | join(",") | if . == "" then "-" else . end)
  ]
| @tsv
'

TURN_USAGE_WAIT_ATTEMPTS=15
TURN_USAGE_WAIT_INTERVAL=0.1
TURN_USAGE_WAIT_WINDOW=1048576

# The transcript is written in batches: the response that ended the turn lands
# in the file about 100 ms after the Stop hook starts. Poll until it is there,
# recognised as an assistant entry that is not a tool call and is newer than
# the previous Stop. Gives up after ATTEMPTS * INTERVAL seconds; only the tail
# of the file is checked so a huge turn does not make each poll slow.
#   $1 transcript path   $2 byte offset of the turn   $3 previous Stop epoch
turn_usage_await_final_response() {
  local transcript="$1" offset="$2" prev_stop_epoch="$3"
  local attempt size from
  for (( attempt = 0; attempt < TURN_USAGE_WAIT_ATTEMPTS; attempt++ )); do
    size=$(wc -c < "$transcript")
    from=$(( size - TURN_USAGE_WAIT_WINDOW ))
    (( from < offset )) && from=$offset
    tail -c "+$((from + 1))" "$transcript" \
      | jq -Rn -e --argjson after "$prev_stop_epoch" '
          [inputs | fromjson?
           | select(.type == "assistant" and .message.stop_reason != "tool_use")
           | (.timestamp // "")[0:19] + "Z" | try fromdateiso8601 catch 0]
          | (last // 0) > $after' >/dev/null 2>&1 && return 0
    sleep "$TURN_USAGE_WAIT_INTERVAL"
  done
}

# Print the turn usage, e.g.
#   토큰 in 652.3k (일반 200 + 캐시 읽기 640.1k + 캐시 쓰기 12k) · out 8.4k · ≈$1.23
# The three input parts are billed at different rates and add up to "in".
# Prints nothing when the turn made no API call or its start offset is unknown.
#   $1 transcript path   $2 transcript byte offset at prompt arrival
#   $3 prompt epoch      $4 file whose mtime is the prompt arrival
#   $5 previous Stop epoch (0 when there was none)
turn_usage_summary() {
  local transcript="$1" offset="$2" start_epoch="$3" prompt_file="$4" prev_stop_epoch="$5"
  [[ -f "$transcript" && "$offset" =~ ^[0-9]+$ ]] || return 0

  turn_usage_await_final_response "$transcript" "$offset" "$prev_stop_epoch"

  local subagent_dir="${transcript%.jsonl}/subagents"
  local total_in uncached cache_read cache_write out cost unpriced
  IFS=$'\t' read -r total_in uncached cache_read cache_write out cost unpriced < <(
    {
      tail -c "+$((offset + 1))" "$transcript"
      if [[ -d "$subagent_dir" ]]; then
        find "$subagent_dir" -name '*.jsonl' -newer "$prompt_file" -exec cat {} +
      fi
    } | jq -Rrn --argjson start "$start_epoch" "$TURN_USAGE_JQ" 2>/dev/null
  ) || return 0
  [[ -n "${total_in:-}" ]] || return 0

  local cost_text
  cost_text=$(LC_ALL=C printf '≈$%.2f' "$cost")
  [[ "$unpriced" != "-" ]] && cost_text="${cost_text} + 가격 미등록 모델(${unpriced})"

  printf '토큰 in %s (일반 %s + 캐시 읽기 %s + 캐시 쓰기 %s) · out %s · %s' \
    "$total_in" "$uncached" "$cache_read" "$cache_write" "$out" "$cost_text"
}
