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
# Additionally, Claude Code's per-project auto-memory path
# (~/.claude/projects/-home-junho/memory) is symlinked to shared/memory so
# all four tools end up reading and writing the same memory files.
#
# Existing real directories are backed up to <path>.bak.<timestamp>. Existing
# symlinks that already point at this repo are left alone. If a memory
# directory already contains files at install time, missing files are merged
# into shared/memory first and the original is moved to .bak before linking.
#
# Pass --dry-run to preview without changing anything.

set -euo pipefail

DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help)
      sed -n '2,21p' "$0" | sed 's/^# \{0,1\}//'
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

run() {
  if [[ $DRY_RUN -eq 1 ]]; then
    echo "DRY: $*"
  else
    echo "RUN: $*"
    eval "$@"
  fi
}

mkdir -p "$HOME/.config"

# --- Phase 1: top-level home symlinks ---
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
    echo "BACKUP: $target -> $backup"
    run "mv \"$target\" \"$backup\""
  fi
  run "ln -s \"$source\" \"$target\""
done

# --- Phase 2: Claude auto-memory unification ---
# Claude Code writes per-project memory to ~/.claude/projects/<slug>/memory/.
# We unify the -home-junho slug into shared/memory. Add slugs to this array
# as new projects need their memory unified.
MEMORY_SLUGS=("-home-junho")

for slug in "${MEMORY_SLUGS[@]}"; do
  mem_dir="$HOME/.claude/projects/$slug/memory"
  shared_target="$REPO_ROOT/shared/memory"

  parent="$HOME/.claude/projects/$slug"
  if [[ ! -d "$parent" ]]; then
    run "mkdir -p \"$parent\""
  fi

  if [[ -L "$mem_dir" ]]; then
    current="$(readlink "$mem_dir")"
    # readlink may give absolute or relative; normalize via realpath
    if [[ "$(realpath -m "$mem_dir" 2>/dev/null || echo "$mem_dir")" == "$shared_target" ]]; then
      echo "OK:    $mem_dir -> shared/memory (already linked)"
      continue
    fi
    echo "WARN:  $mem_dir is a symlink to $current"
    run "rm \"$mem_dir\""
  elif [[ -d "$mem_dir" ]]; then
    # Real directory — merge any files we don't already have, then back up.
    echo "MERGE: existing $mem_dir -> shared/memory (only files missing in shared)"
    if [[ $DRY_RUN -eq 0 ]]; then
      shopt -s nullglob dotglob
      for f in "$mem_dir"/*; do
        name="$(basename "$f")"
        if [[ ! -e "$shared_target/$name" ]]; then
          echo "  MERGE: $name (new)"
          cp -a "$f" "$shared_target/$name"
        else
          if cmp -s "$f" "$shared_target/$name"; then
            echo "  SKIP:  $name (identical)"
          else
            echo "  KEEP:  shared/memory/$name (differs from existing — backup will preserve original)"
          fi
        fi
      done
      shopt -u nullglob dotglob
    fi
    backup="$mem_dir.bak.$TS"
    echo "BACKUP: $mem_dir -> $backup"
    run "mv \"$mem_dir\" \"$backup\""
  fi

  run "ln -s \"$shared_target\" \"$mem_dir\""
done

echo
echo "Done. Run 'scripts/doctor.sh' to verify."
