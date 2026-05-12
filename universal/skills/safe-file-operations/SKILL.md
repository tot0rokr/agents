---
name: safe-file-operations
description: Use this skill whenever about to read, edit, or create a file on disk. Triggers include calling cat/head/tail/less on a file of unknown size, planning to use sed -i, sed -e in-place, awk -i inplace, or find -exec to mutate files, performing regex-based search-and-replace across files, or writing/overwriting any file via shell redirection. Enforces inspection-before-read using ls and wc, and replaces in-place shell mutations with the agent's own file-editing tools so every change is targeted and auditable.
---

# Safe File Operations

## Reading: inspect before read

Never dump a file blindly. First check size and length so the read can be scoped:

```bash
ls -lh <file> \
&& echo "---" \
&& wc -l <file>
```

Decide which portion is actually needed, then read with a line range using the agent's `view` tool rather than `cat`. For very large files, prefer `grep -n <pattern> <file>` to locate regions of interest, then view those line ranges specifically.

## Editing: no in-place shell mutations

Do not modify files with `cat > file`, `cat >> file`, `sed -i`, `awk -i inplace`, `find ... -exec sed ...`, or any other shell command that rewrites file contents in place. These edits are not reviewable and easily corrupt files on a typo.

Use the agent's file tools instead:
- `str_replace` for targeted, surgical edits to existing files
- `create_file` for brand-new files or intentional full rewrites

## Regex-based edits: locate, then edit one by one

When a change needs to be applied at multiple matches of a pattern, do not chain a regex into `sed -i`. Instead:

1. Locate all matches first to verify the regex catches exactly what is intended and nothing else:
   ```bash
   grep -nE '<pattern>' <files>
   ```
2. Review the match list. If any false positive appears, refine the pattern and re-run grep.
3. Apply each confirmed match individually using `str_replace`, with enough surrounding context in `old_str` to make each replacement unique.

This trades a small amount of speed for full control: every edit is visible in the conversation and can be reverted precisely.
