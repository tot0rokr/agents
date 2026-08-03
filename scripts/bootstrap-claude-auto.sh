#!/usr/bin/env bash
# bootstrap-claude-auto.sh — install claude-account-switcher (claude-auto) and
# point this home's `claude` wrapper at it, so accounts rotate automatically.
#
#   scripts/bootstrap-claude-auto.sh [--dry-run] [--repo URL] [--dir DIR]
#
# Idempotent: re-running updates the checkout and re-checks the wrapper.
# Safe to skip: if the tool can't be fetched, nothing else is touched.
set -uo pipefail

REPO_URL="${CLAUDE_AUTO_REPO:-https://github.com/tot0rokr/claude-switcher.git}"
DEST="${CLAUDE_AUTO_SRC:-$HOME/claude-switcher}"
DRY=0

while [ $# -gt 0 ]; do case "$1" in
  --dry-run) DRY=1; shift;;
  --repo) REPO_URL="$2"; shift 2;;
  --dir)  DEST="$2"; shift 2;;
  -h|--help) sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; exit 0;;
  *) echo "unknown arg: $1" >&2; exit 2;;
esac; done

say()  { printf '  %s\n' "$*"; }
warn() { printf '  ⚠ %s\n' "$*" >&2; }
run()  { [ "$DRY" = 1 ] && { printf '  [dry-run] %s\n' "$*"; return 0; }; eval "$@"; }

echo "== claude-auto bootstrap =="
command -v git >/dev/null 2>&1 || { warn "git not found — skipped"; exit 0; }

# 1) fetch / update the checkout
if [ -d "$DEST/.git" ]; then
  run "git -C '$DEST' pull -q" && say "updated $DEST" || warn "pull failed (keeping existing checkout)"
elif [ -e "$DEST" ]; then
  warn "$DEST exists but is not a git checkout — skipped"; exit 0
else
  if run "git clone -q '$REPO_URL' '$DEST'"; then
    [ "$DRY" = 1 ] || say "cloned → $DEST"
  else warn "clone failed ($REPO_URL) — skipped"; exit 0; fi
fi
# In dry-run the checkout doesn't exist, so stop before inspecting it.
[ "$DRY" = 1 ] && [ ! -d "$DEST" ] && { say "[dry-run] would run $DEST/install.sh, then patch the claude wrapper in ~/.bashrc"; exit 0; }

# 2) run the tool's own installer (binaries + statusLine sensor + config home).
#    --seed-current captures whatever account is logged in right now, if any.
[ -x "$DEST/install.sh" ] || { warn "no install.sh in $DEST — skipped"; exit 0; }
# Seed the logged-in account only on a first install. With slots already stored,
# seeding would add a duplicate of whichever account happens to be active.
SEED=""
ACCTS="${CLAUDE_AUTO_HOME:-$HOME/.claude-accounts}/config/accounts.list"
if [ -f "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/.credentials.json" ] \
   && ! grep -qE '^[^[:space:]#]' "$ACCTS" 2>/dev/null; then
  SEED="--seed-current"
fi
run "bash '$DEST/install.sh' $SEED" || { warn "installer failed"; exit 0; }

# 3) route this home's `claude` wrapper through claude-auto.
#    A bare alias would shadow a plugin wrapper, so patch the wrapper instead:
#    only the launch line changes, every flag it passes is preserved.
RC="$HOME/.bashrc"
if [ ! -f "$RC" ]; then
  say "no ~/.bashrc — add this yourself: alias claude='claude-auto'"
elif grep -q 'claude-auto' "$RC" 2>/dev/null; then
  say "wrapper already routes through claude-auto"
elif grep -qE '^[[:space:]]*(function[[:space:]]+)?claude[[:space:]]*\(\)' "$RC"; then
  # A wrapper function exists — rewrite its `command claude …` launch line.
  if [ "$DRY" = 1 ]; then
    say "[dry-run] would rewrite the 'command claude' line in $RC"
  else
    cp -p "$RC" "$RC.pre-claude-auto.$(date +%Y%m%d-%H%M%S).bak"
    python3 - "$RC" <<'PY'
import re, sys
p = sys.argv[1]; s = open(p).read()
# `command claude ARGS` → route through claude-auto when it is installed
pat = re.compile(r'^(\s*)command claude(\s.*)$', re.M)
def repl(m):
    ind, args = m.group(1), m.group(2)
    return (f'{ind}if command -v claude-auto >/dev/null 2>&1; then\n'
            f'{ind}    claude-auto{args}\n'
            f'{ind}else\n'
            f'{ind}    command claude{args}\n'
            f'{ind}fi')
new, n = pat.subn(repl, s, count=1)
if n:
    open(p, 'w').write(new); print(f"  patched the claude wrapper in {p}")
else:
    print(f"  ⚠ wrapper found but no 'command claude' line — patch it by hand", file=sys.stderr)
PY
    bash -n "$RC" || warn "$RC failed syntax check — restore from the .bak next to it"
  fi
else
  # No wrapper at all → a plain alias is enough.
  run "printf '\n# claude-account-switcher\ncommand -v claude-auto >/dev/null 2>&1 && alias claude=\"claude-auto\"\n' >> '$RC'" \
    && say "added 'alias claude=claude-auto' to $RC"
fi

echo
say "next: claude-auto login <name>   (add each account)"
say "      claude-auto status"
