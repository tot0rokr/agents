#!/usr/bin/env bash
# Install per-tool symlinks from this repo into the user's home directory.
#
# After running, each CLI agent reads its config from this repo:
#   ~/.claude            -> agents/claude
#   ~/.codex             -> agents/codex
#   ~/.config/opencode   -> agents/opencode
#   ~/.gemini            -> agents/gemini
#   ~/.agents            -> agents/universal     (codex/opencode/gemini fallback)
#
# Three phases run after the symlinks are placed:
#
#   Phase 1 — Top-level home symlinks. Existing real directories are backed up
#             to <path>.bak.<timestamp>. Symlinks already pointing at this repo
#             are left alone.
#
#   Phase 2 — Claude per-project auto-memory unification. Every
#             ~/.claude/projects/<slug>/memory found in the fresh ~/.claude
#             backup is merged into shared/memory and replaced with a symlink,
#             so all four agents read and write the same memory pool.
#
#   Phase 3 — Runtime data restore. After ~/.claude is symlinked, runtime files
#             that Claude Code recreates fresh (credentials, sessions, history,
#             transcripts, file-history, local permissions) are restored from
#             the fresh ~/.claude.bak.<timestamp>. Skipped if no fresh backup
#             exists (e.g., on re-run after a successful install).
#
# Pass --dry-run to preview without changing anything.

set -euo pipefail

DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help)
      sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "unknown arg: $arg" >&2; exit 2 ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TS="$(date +%Y%m%d-%H%M%S)"

declare -A LINKS=(
  ["$HOME/.claude"]="$REPO_ROOT/claude"
  ["$HOME/.codex"]="$REPO_ROOT/codex"
  ["$HOME/.config/opencode"]="$REPO_ROOT/opencode"
  ["$HOME/.gemini"]="$REPO_ROOT/gemini"
  ["$HOME/.agents"]="$REPO_ROOT/universal"
)

# Backups created in this run. Keyed by target path, value is backup path.
# Phase 2/3 only act on backups in this map — never on stale .bak.<old-TS>.
declare -A FRESH_BACKUPS=()

run() {
  if [[ $DRY_RUN -eq 1 ]]; then
    echo "DRY: $*"
  else
    echo "RUN: $*"
    eval "$@"
  fi
}

mkdir -p "$HOME/.config"

# ============================================================================
# Phase 1 — top-level home symlinks
# ============================================================================
for target in "${!LINKS[@]}"; do
  source="${LINKS[$target]}"
  if [[ -L "$target" ]]; then
    current="$(readlink "$target")"
    if [[ "$current" == "$source" ]]; then
      echo "OK:    $target -> $source (already linked)"
      continue
    fi
    echo "WARN:  $target is a symlink to $current"
    run "rm \"$target\""
  elif [[ -e "$target" ]]; then
    backup="$target.bak.$TS"
    FRESH_BACKUPS["$target"]="$backup"
    echo "BACKUP: $target -> $backup"
    run "mv \"$target\" \"$backup\""
  fi
  run "ln -s \"$source\" \"$target\""
done

CLAUDE_BAK="${FRESH_BACKUPS[$HOME/.claude]:-}"
SHARED_MEMORY="$REPO_ROOT/shared/memory"

# ============================================================================
# Phase 2 — Claude auto-memory unification
# ============================================================================
# Discover every slug that has a memory/ dir in the fresh backup. Fall back to
# the current-cwd slug so a fresh-machine install still creates the link.
declare -a MEMORY_SLUGS=()
if [[ -n "$CLAUDE_BAK" && -d "$CLAUDE_BAK/projects" ]]; then
  shopt -s nullglob
  for d in "$CLAUDE_BAK/projects"/*/memory; do
    [[ -e "$d" ]] || continue
    slug=$(basename "$(dirname "$d")")
    MEMORY_SLUGS+=("$slug")
  done
  shopt -u nullglob
fi
# Always include the current cwd's slug so /resume here has a memory symlink
# even on first install with no backup.
CWD_SLUG="$(pwd | sed 's|/|-|g')"
if [[ ! " ${MEMORY_SLUGS[*]:-} " =~ " $CWD_SLUG " ]]; then
  MEMORY_SLUGS+=("$CWD_SLUG")
fi

for slug in "${MEMORY_SLUGS[@]:-}"; do
  mem_link="$HOME/.claude/projects/$slug/memory"
  parent="$(dirname "$mem_link")"

  # Merge any pre-existing files from the backup into shared/memory first.
  bak_mem="$CLAUDE_BAK/projects/$slug/memory"
  if [[ -n "$CLAUDE_BAK" && -d "$bak_mem" ]]; then
    if [[ $DRY_RUN -eq 0 ]]; then
      shopt -s nullglob dotglob
      for f in "$bak_mem"/*; do
        [[ -e "$f" ]] || continue
        name="$(basename "$f")"
        if [[ ! -e "$SHARED_MEMORY/$name" ]]; then
          cp -a "$f" "$SHARED_MEMORY/$name"
          echo "  MERGE: $slug/memory/$name -> shared/memory (new)"
        elif cmp -s "$f" "$SHARED_MEMORY/$name"; then
          echo "  SKIP:  $slug/memory/$name (identical)"
        else
          echo "  KEEP:  shared/memory/$name (differs; backup preserves $slug version)"
        fi
      done
      shopt -u nullglob dotglob
    else
      echo "DRY: merge $bak_mem/* into $SHARED_MEMORY (only missing files)"
    fi
  fi

  run "mkdir -p \"$parent\""
  if [[ -L "$mem_link" ]]; then
    current="$(readlink "$mem_link")"
    resolved="$(realpath -m "$mem_link" 2>/dev/null || echo "$mem_link")"
    if [[ "$resolved" == "$SHARED_MEMORY" ]]; then
      echo "OK:    $mem_link -> shared/memory (already linked)"
      continue
    fi
    echo "WARN:  $mem_link is a symlink to $current; replacing"
    run "rm \"$mem_link\""
  elif [[ -e "$mem_link" ]]; then
    # Should be rare — after Phase 1, ~/.claude is a fresh symlink and this
    # path won't exist yet. Handle defensively.
    backup="$mem_link.bak.$TS"
    echo "BACKUP: $mem_link -> $backup"
    run "mv \"$mem_link\" \"$backup\""
  fi

  run "ln -s \"$SHARED_MEMORY\" \"$mem_link\""
done

# ============================================================================
# Phase 3 — restore Claude runtime data from the fresh ~/.claude backup
# ============================================================================
if [[ -z "$CLAUDE_BAK" || ! -d "$CLAUDE_BAK" ]]; then
  echo
  echo "Phase 3: no fresh ~/.claude backup from this run; skipping restore."
else
  echo
  echo "Phase 3: restoring runtime data from $CLAUDE_BAK"
  CUR="$HOME/.claude"

  # --- .credentials.json (avoids needing /login after install) ---
  if [[ -e "$CLAUDE_BAK/.credentials.json" && ! -e "$CUR/.credentials.json" ]]; then
    run "cp -a \"$CLAUDE_BAK/.credentials.json\" \"$CUR/.credentials.json\""
  fi

  # --- history.jsonl (used by /resume search; safe to concat as jsonl) ---
  if [[ -e "$CLAUDE_BAK/history.jsonl" ]]; then
    if [[ -e "$CUR/history.jsonl" && -s "$CUR/history.jsonl" ]]; then
      run "cat \"$CLAUDE_BAK/history.jsonl\" \"$CUR/history.jsonl\" > \"$CUR/history.jsonl.new\" && mv \"$CUR/history.jsonl.new\" \"$CUR/history.jsonl\""
    else
      run "cp -a \"$CLAUDE_BAK/history.jsonl\" \"$CUR/history.jsonl\""
    fi
  fi

  # --- sessions/ ---
  if [[ -d "$CLAUDE_BAK/sessions" && ! -e "$CUR/sessions" ]]; then
    run "cp -a \"$CLAUDE_BAK/sessions\" \"$CUR/sessions\""
  fi

  # --- file-history/ (merge; never overwrite newer files) ---
  if [[ -d "$CLAUDE_BAK/file-history" ]]; then
    run "mkdir -p \"$CUR/file-history\""
    run "rsync -a --ignore-existing \"$CLAUDE_BAK/file-history/\" \"$CUR/file-history/\""
  fi

  # --- projects/<slug>/*.jsonl (per-project transcripts for /resume) ---
  if [[ -d "$CLAUDE_BAK/projects" ]]; then
    shopt -s nullglob
    for proj in "$CLAUDE_BAK/projects"/*; do
      [[ -d "$proj" ]] || continue
      slug=$(basename "$proj")
      dest="$CUR/projects/$slug"
      transcripts=("$proj"/*.jsonl)
      [[ ${#transcripts[@]} -eq 0 ]] && continue
      run "mkdir -p \"$dest\""
      for f in "${transcripts[@]}"; do
        name="$(basename "$f")"
        if [[ -e "$dest/$name" ]]; then
          # UUID collision with a live transcript (current session).
          # Preserve the backup with a non-.jsonl suffix so /resume ignores it.
          preserved="$dest/${name%.jsonl}.pre-install.jsonl.bak"
          if [[ ! -e "$preserved" ]]; then
            run "cp -a \"$f\" \"$preserved\""
            echo "  KEPT live $slug/$name (backup saved as $(basename "$preserved"))"
          else
            echo "  SKIP:  $slug/$name (preserved backup already exists)"
          fi
        else
          run "cp -a \"$f\" \"$dest/$name\""
          echo "  RESTORED $slug/$name"
        fi
      done
    done
    shopt -u nullglob
  fi

  # --- settings.local.json (merge permissions.allow via jq union) ---
  if [[ -e "$CLAUDE_BAK/settings.local.json" ]]; then
    local_cur="$CUR/settings.local.json"
    if command -v jq >/dev/null 2>&1; then
      if [[ -e "$local_cur" ]]; then
        run "jq --slurpfile bak \"$CLAUDE_BAK/settings.local.json\" '.permissions.allow = ((.permissions.allow // []) + (\$bak[0].permissions.allow // []) | unique)' \"$local_cur\" > \"$local_cur.new\" && mv \"$local_cur.new\" \"$local_cur\""
      else
        run "cp -a \"$CLAUDE_BAK/settings.local.json\" \"$local_cur\""
      fi
    else
      echo "WARN:  jq not installed; cannot merge settings.local.json. Backup at $CLAUDE_BAK/settings.local.json"
    fi
  fi
fi

echo
echo "Done. Run 'scripts/doctor.sh' to verify."
