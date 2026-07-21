---
name: git-commit-workflow
description: Use this skill whenever about to run git commit, compose a commit message, or invoke any destructive git operation such as git reset, git restore, git checkout -- <file>, git clean, or any history-rewriting command (rebase, amend, push --force). Triggers also include staging changes with git add and any moment the agent has modified files inside a git-managed repository. Enforces commit hygiene (only commit what this agent changed, base the message on actual git status and git diff output) and a hard stop before any destructive operation that could lose user work.
---

# Git Commit Workflow

## Stage only what THIS work changed

A working tree often contains modifications from earlier sessions, the user's own hand-edits, or other agents. Sweeping everything in produces commits that mix unrelated work and — worse — can publish files the user deliberately kept out of git (memory snippets containing secrets, in-progress drafts, local-only configs). The verification procedure below is mandatory before every `git add`.

### Required procedure before staging

1. **Inventory the current state.** Run these in order and read every line of every output:

   ```bash
   git status --short
   git diff
   git diff --staged   # only if anything is already staged
   ```

   `git status --short` lists every modified, staged, untracked, and deleted path. The diffs show the actual content changes. You need all three to know what's there.

2. **Classify each entry.** For every path in `git status --short`, decide which bucket it belongs to:
   - **This work** — a file this agent changed in service of the current task. Goes into the commit.
   - **Pre-existing / unrelated** — modified before this session, or by another tool (e.g. a plugin migrated its own config). Stays out.
   - **Deliberately uncommitted** — the user said "don't commit this", or it's known working-tree-only state (e.g. memory files with PII, `*.local.json`). Stays out.
   - **Unsure** — stop and ask the user before staging. Don't guess.

3. **Stage only your changes — by explicit path, and by hunk when a file is mixed.**

   - **Whole file is yours** → stage it by explicit path:

     ```bash
     git add path/to/specific-file.py path/to/other-file.md
     ```

     If the file list is long, list every path on its own line; the verbosity is the point.

   - **A file mixes changes that belong in this commit with ones that don't** (classic case: your one new line lives in a `MEMORY.md` / config that also holds working-tree-only PII or another session's edits) → never stage the whole file, and do not think in whole hunks either. git collapses nearby edits into a single hunk, so several unrelated changes routinely appear merged together and a plain `git add -p` `y` would take all of them. Select only the **exact lines** this commit should contain, named explicitly:

     - **Preferred — build a patch of exactly those lines and apply it to the index.** Explicit, reviewable, and works non-interactively:

       ```bash
       git diff -- path/to/mixed-file.md > /tmp/all.patch
       # hand-trim /tmp/all.patch down to only the +/- lines this commit should include,
       # keeping enough surrounding context lines that the hunk still applies
       git apply --cached --check /tmp/my-lines.patch   # dry-run: verify it applies
       git apply --cached /tmp/my-lines.patch           # then stage exactly those lines
       ```

     - **Interactive alternative** — `git add -p path/to/mixed-file.md`, but its per-hunk `y`/`n` is not line-precise: use `s` to split as far as git will, and `e` to hand-edit the hunk buffer (delete the `+`/`-` lines you don't want) whenever a split still leaves your line merged with others.

   **Forbidden — no exceptions**: `git add -A`, `git add .`, `git add -u`, `git add :/`, or any glob that could absorb unrelated changes.

4. **Verify staging matches intent.** After staging, run `git status --short` once more and `git diff --staged` again. Compare what's staged to your bucket-1 list from step 2. If anything else snuck in, `git restore --staged <path>` it and re-verify. When you hunk-staged a mixed file, this step is mandatory, not optional: confirm every excluded hunk (PII, another session's edits) still shows in `git diff` (working tree) but is **absent** from `git diff --staged`.

### Failure mode this rule blocks

A typical violation: the agent is doing a tree-wide rename or refactor and reaches for `git add -A` so the renames register correctly. That command also stages every other modified file in the tree, including any memory or note file the user is keeping working-tree-only. Once committed and pushed (especially to a public repo), the leaked file is in history — force-push only partially scrubs it. **Stage the rename explicitly**: list the old and new paths, the imports, the config, the tests. Verbose is correct.

## Write the message from the diff, not from memory

The commit message must describe what is actually being committed, not what the agent intended to do. Before writing the message:

```bash
git status \
&& echo "--- staged diff ---" \
&& git diff --staged
```

Read the staged diff and write the message from what is actually there. If the diff and the intended change disagree, fix the staging before writing the message.

## Commit messages: always use a heredoc (`-F -`)

For every commit message — single-line or multi-paragraph — pipe the whole message through `git commit -F -` (heredoc), or `-F <file>`. This gives full control over wrapping: wrap prose at ~72 columns *within* a paragraph, and put a single blank line only *between* paragraphs (and after the subject).

```bash
git commit -F - <<'EOF'
subsystem: short imperative summary

Explain what changed and why in a normal wrapped paragraph. Reference the
problem this addresses and any non-obvious decisions — these lines flow
together because they are one paragraph, not separate flags.

- bullet points are fine; keep the body tight, not a wall of text

Refs: #123
EOF
```

Never build a commit message from `-m` flags — not even a single-line one. git turns each `-m` into its own paragraph with a blank line between, so a body split across several `-m` flags becomes disconnected half-sentences. The heredoc form above is the only form to use.

## Destructive operations require explicit user approval

Never invoke any of these without the user explicitly asking for them in the current session:

- `git reset` (any mode, especially `--hard`)
- `git restore` (any flags)
- `git checkout -- <file>` or `git checkout <ref> -- <file>`
- `git clean`
- `git rebase`, `git commit --amend` on already-pushed commits
- `git push --force` or `--force-with-lease`
- `git branch -D`, `git tag -d`

If one of these seems necessary, stop and ask the user, naming the exact command and the files or refs it would affect. Wait for an explicit go-ahead before running it.
