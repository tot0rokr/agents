#!/usr/bin/env bash
# Convert shared/commands/*.md (Markdown with YAML frontmatter) to
# gemini/commands/*.toml (Gemini CLI's required format).
#
# Frontmatter fields: description, model (ignored — Gemini commands carry
# no model field). Markdown body becomes the `prompt` field.
#
# Subdirectories under shared/commands/ map to namespace separators:
# shared/commands/git/commit.md -> gemini/commands/git/commit.toml
# (Gemini renders these as `/git:commit`.)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC_DIR="$REPO_ROOT/shared/commands"
DST_DIR="$REPO_ROOT/gemini/commands"

command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 1; }

# Clear stale generated files (keep .gitkeep).
find "$DST_DIR" -name '*.toml' -type f -delete

python3 - "$SRC_DIR" "$DST_DIR" <<'PY'
import pathlib, re, sys, json

src = pathlib.Path(sys.argv[1])
dst = pathlib.Path(sys.argv[2])

frontmatter_re = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)

def parse_frontmatter(text):
    m = frontmatter_re.match(text)
    if not m:
        return {}, text
    fm_text, body = m.group(1), m.group(2)
    fm = {}
    for line in fm_text.splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        fm[k.strip()] = v.strip().strip('"').strip("'")
    return fm, body

def toml_escape(s):
    # use triple-quoted basic string for multi-line prompts
    return '"""\n' + s.replace('"""', '\\"""') + '\n"""'

for md in src.rglob("*.md"):
    rel = md.relative_to(src)
    out = dst / rel.with_suffix(".toml")
    out.parent.mkdir(parents=True, exist_ok=True)
    fm, body = parse_frontmatter(md.read_text())
    desc = fm.get("description", "")
    lines = []
    if desc:
        lines.append(f'description = {json.dumps(desc)}')
    lines.append(f"prompt = {toml_escape(body.strip())}")
    out.write_text("\n".join(lines) + "\n")
    print(f"wrote {out}")
PY
