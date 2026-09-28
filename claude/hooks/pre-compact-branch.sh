#!/usr/bin/env bash
# PreCompact hook: preserve the full conversation as a new resumable session
# right before compaction makes it unreachable to /rewind.
#
# File-level equivalent of "/rename + /branch" (zero context cost, works for
# manual and auto compaction, even mid-turn):
#   1. copy the transcript to a fresh session UUID (sessionId rewritten)
#   2. append custom-title + ai-title lines so the snapshot is recognizable in /resume
#   3. copy file-history/<sid> so /rewind file restores work in the snapshot
#   4. record orig->snapshot in a registry; prune old snapshots (keep last N)
#
# Relies on undocumented internals (ai-title lines, file-history layout), so it
# probes the transcript format first and no-ops with a bell warning when
# anything looks off. It must never break compaction: every path exits 0.
#
# Knobs: PRECOMPACT_BRANCH_DISABLE=1 (skip), PRECOMPACT_BRANCH_KEEP=N (default 3)
set -uo pipefail

KEEP="${PRECOMPACT_BRANCH_KEEP:-3}"
STATE_DIR="$HOME/.claude/hooks/state"
REGISTRY="$STATE_DIR/precompact-branches.jsonl"
FH_ROOT="$HOME/.claude/file-history"

warn() {
    printf 'pre-compact-branch: %s\n' "$1" >&2
    command -v bell-send >/dev/null 2>&1 &&
        bell-send --title "pre-compact-branch" --body "$1" >/dev/null 2>&1
    return 0
}

[ -n "${PRECOMPACT_BRANCH_DISABLE:-}" ] && exit 0
command -v jq >/dev/null 2>&1 || exit 0
command -v uuidgen >/dev/null 2>&1 || { warn "uuidgen missing — snapshot skipped"; exit 0; }

input="$(cat 2>/dev/null || true)"
sid="$(jq -r '.session_id // empty' <<<"$input" 2>/dev/null)"
tp="$(jq -r '.transcript_path // empty' <<<"$input" 2>/dev/null)"
trigger="$(jq -r '.trigger // "unknown"' <<<"$input" 2>/dev/null)"
[ -n "$sid" ] && [ -n "$tp" ] && [ -f "$tp" ] || exit 0

# Only snapshot real interactive sessions (excludes subagent/task transcripts).
case "$tp" in
    "$HOME/.claude/projects/"*) ;;
    *) exit 0 ;;
esac

# Format probe: first line must be JSON with a .type; skip trivial sessions.
head -1 "$tp" | jq -e 'has("type")' >/dev/null 2>&1 ||
    { warn "transcript format probe failed — snapshot skipped ($tp)"; exit 0; }
grep -q '"type":"user"' "$tp" && grep -q '"type":"assistant"' "$tp" || exit 0

# Hijack countermeasures (observed twice on 2026-08-25, v2.1.243): at compact,
# the live CC process rotates its session and resolves the continuation BY
# CONTENT (shared message uuids), so an unmarked uuid-identical copy gets
# adopted as the live session — regardless of which project dir it sits in.
# Defenses, strongest first:
#   1. forkedFrom stamps on every message line (what native /branch does — the
#      only visible marker distinguishing a branch from a continuation)
#   2. rewritten line cwd + a global bucket project, so no cwd/dir-based
#      matcher can tie the snapshot to the live project
# Cross-project resume ("claude --resume <id>") always works; to ALSO see the
# bucket in /resume + Ctrl+A, register it once per machine: run `claude` inside
# $SNAP_CWD and accept the trust prompt (headless runs don't register).
SNAP_CWD="$HOME/.claude-precompact-snapshots"
snap_slug="$(printf '%s' "$SNAP_CWD" | sed 's/[^A-Za-z0-9]/-/g')"
snap_dir="$HOME/.claude/projects/$snap_slug"
mkdir -p "$SNAP_CWD" "$snap_dir" || { warn "cannot create $snap_dir"; exit 0; }
new_id="$(uuidgen)"
snap="$snap_dir/$new_id.jsonl"
tmp="$snap.tmp"

# Rewrite sessionId per line and stamp forkedFrom lineage on message lines,
# matching native /branch output (verified 2026-08-25 on v2.1.243: /branch
# keeps message uuids identical and marks each copied line with
# forkedFrom={sessionId, messageUuid}). fromjson? drops a torn last line.
jq -cR --arg sid "$new_id" --arg orig "$sid" --arg snapcwd "$SNAP_CWD" \
    'fromjson? | select(. != null)
     | if has("sessionId") then .sessionId = $sid else . end
     | if has("uuid") then .forkedFrom = {sessionId: $orig, messageUuid: .uuid} else . end
     | if has("cwd") then .cwd = $snapcwd else . end' \
    "$tp" > "$tmp" 2>/dev/null &&
    [ -s "$tmp" ] ||
    { rm -f "$tmp"; warn "transcript rewrite failed — snapshot skipped"; exit 0; }

# "/rename": base title priority mirrors the picker's — custom-title (set via
# /rename, outranks everything), then ai-title, then first user text.
title="$(jq -r 'select(.type=="custom-title") | .customTitle // empty' "$tmp" 2>/dev/null | tail -1)"
[ -n "$title" ] ||
    title="$(jq -r 'select(.type=="ai-title") | .aiTitle // empty' "$tmp" 2>/dev/null | tail -1)"
if [ -z "$title" ]; then
    title="$(jq -r 'select(.type=="user") | .message.content
                    | if type=="string" then . elif type=="array"
                      then (map(select(type=="object" and .type=="text") | .text) | join(" "))
                      else empty end' "$tmp" 2>/dev/null |
             grep -m1 . | tr -d '\n' | cut -c1-48)"
fi
snap_title="${title:-session} ⎇ pre-compact $(date +'%Y-%m-%d %H:%M')"
# Append BOTH title kinds: the custom-title must come last to override any
# custom-title lines copied from a /rename'd original; ai-title is the fallback
# display for anything that ignores custom titles.
jq -cn --arg t "$snap_title" --arg sid "$new_id" \
    '{type:"ai-title", aiTitle:$t, sessionId:$sid}' >> "$tmp"
jq -cn --arg t "$snap_title" --arg sid "$new_id" \
    '{type:"custom-title", customTitle:$t, sessionId:$sid}' >> "$tmp"
mv "$tmp" "$snap" || { rm -f "$tmp"; warn "snapshot move failed"; exit 0; }

# "/rewind": carry the file-history checkpoints (hardlink, fall back to copy).
if [ -d "$FH_ROOT/$sid" ] && [ ! -e "$FH_ROOT/$new_id" ]; then
    cp -al "$FH_ROOT/$sid" "$FH_ROOT/$new_id" 2>/dev/null ||
        cp -a "$FH_ROOT/$sid" "$FH_ROOT/$new_id" 2>/dev/null ||
        warn "file-history copy failed — snapshot resumes, but /rewind file restore may not work"
fi

mkdir -p "$STATE_DIR"
jq -cn --arg ts "$(date -Is)" --arg orig "$sid" --arg snap "$new_id" \
    --arg title "$snap_title" --arg trig "$trigger" --arg dir "$snap_dir" \
    '{ts:$ts, orig:$orig, snapshot:$snap, title:$title, trigger:$trig, dir:$dir}' >> "$REGISTRY"

# Prune: keep the newest KEEP snapshots per original session. Deletes only
# registry-listed UUIDs, i.e. files this hook created. Skipped on lock contention.
prune() {
    exec 9>>"$STATE_DIR/.registry.lock" || return 0
    flock -n 9 || return 0
    local olds id tmpreg
    olds="$(jq -r --arg orig "$sid" 'select(.orig==$orig) | .snapshot' "$REGISTRY" 2>/dev/null |
            head -n -"$KEEP")"
    [ -n "$olds" ] || return 0
    tmpreg="$(mktemp "$STATE_DIR/.registry.XXXXXX")" || return 0
    cp "$REGISTRY" "$tmpreg" || { rm -f "$tmpreg"; return 0; }
    while IFS= read -r id; do
        [[ "$id" =~ ^[0-9a-fA-F-]{36}$ ]] || continue
        rm -f "$snap_dir/$id.jsonl"
        [ -d "$FH_ROOT/$id" ] && rm -rf "${FH_ROOT:?}/$id"
        grep -v "\"snapshot\":\"$id\"" "$tmpreg" > "$tmpreg.2" && mv "$tmpreg.2" "$tmpreg"
    done <<<"$olds"
    mv "$tmpreg" "$REGISTRY"
}
prune 2>/dev/null || true

exit 0
