---
name: git-commit-workflow
description: Use this skill whenever about to run git commit, compose a commit message, or invoke any destructive git operation such as git reset, git restore, git checkout -- <file>, git clean, or any history-rewriting command (rebase, amend, push --force). Triggers also include staging changes with git add and any moment the agent has modified files inside a git-managed repository. Korean triggers include "커밋해", "커밋하자", "커밋 메시지 써줘", "스테이징해", "되돌려", "리셋해", "리베이스해", "커밋 메시지 고쳐". Enforces commit hygiene (only commit what this agent changed, base the message on actual git status and git diff output) and a hard stop before any destructive operation that could lose user work.
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

5. **Check the staged diff for secrets without printing them.** List only the file names that match, so no value lands in the transcript:

   ```bash
   git diff --cached -i -G'password|passwd|secret|api[_-]?key|token|BEGIN .*PRIVATE KEY' --name-only
   ```

   Open each listed file and judge it yourself. If a real secret is staged, unstage it and tell the user; a secret that was already pushed has to be rotated first, then purged from history.

### Failure mode this rule blocks

A typical violation: the agent is doing a tree-wide rename or refactor and reaches for `git add -A` so the renames register correctly. That command also stages every other modified file in the tree, including any memory or note file the user is keeping working-tree-only. Once committed and pushed (especially to a public repo), the leaked file is in history — force-push only partially scrubs it. **Stage the rename explicitly**: list the old and new paths, the imports, the config, the tests. Verbose is correct.

## Prepare the message

- Read the actual staged diff for a new commit, or `git show <commit>` for a rewrite. Describe only that change.
- Follow the repository's documented message and release rules. Otherwise use the format and type definitions below.
- Separate independent purposes when preparing commits. Keep a feature or fix with its related tests and documentation. Do not use a vague type to hide mixed changes.
- When only rewording an existing commit, describe its full diff without changing its contents or splitting history unless requested.

## Subject and type

Use `type(scope): Subject`; add `!` immediately before `:` for a breaking change.

- Use lowercase type and scope, an imperative subject, and no trailing period. Aim for at most 70 characters including the prefix.
- Name the result and affected condition. Avoid vague subjects such as `Fix bug` or `Update code`.
- Use one stable module or feature name as scope; omit it when no useful scope applies. Put issue references in the footer.
- Select the type by purpose, not file extension or line count. Treat the additional types below as local conventions, not a mandatory Conventional Commits list.

| Type       | Use for                                           | Body focus                                               |
| ---------- | ------------------------------------------------- | -------------------------------------------------------- |
| `feat`     | New user or caller capability                     | Need, interface, defaults, supported cases               |
| `fix`      | Incorrect behavior                                | Trigger, symptom, confirmed cause, corrected behavior    |
| `refactor` | Structure changes preserving the contract         | Structural constraint, new boundary, preserved contract  |
| `perf`     | Lower execution or resource cost                  | Workload, bottleneck, mechanism, evidence, trade-off     |
| `docs`     | Documentation or explanatory text only            | Missing or incorrect guidance and its correction         |
| `test`     | Tests or test infrastructure only                 | Missing scenario or instability, new assertion           |
| `style`    | Mechanical formatting without behavior changes    | Formatting rule and scope; omit obvious body             |
| `build`    | Build, packaging, toolchain, routine dependencies | Build constraint, change, artifact or environment impact |
| `ci`       | CI workflow and execution conditions              | Pipeline gap, trigger or job change, effect              |
| `chore`    | Repository upkeep outside other types             | Specific maintenance need and scope                      |
| `revert`   | Undoing an identified change                      | Original SHA, reason, reverted scope, restored behavior  |

- Classify UI behavior as `feat` or `fix`, not formatting `style`. A fix with regression tests remains `fix`.
- Use `fix(deps)` for a dependency change that repairs a runtime defect or vulnerability; use `build(deps)` for routine maintenance.
- Classify configuration and migration changes by their effect. Do not label new options or changed error behavior as a behavior-preserving refactor.

## Write the body

- Omit the body when the subject fully explains a trivial change. Otherwise begin with the concrete problem or need and the condition under which it matters.
- For a fix, give the trigger, symptom, and confirmed cause. When the cause is uncertain, state only what the evidence supports.
- Connect the solution to its purpose and state the resulting behavior. Include meaningful contract changes in inputs, outputs, defaults, precedence, errors, ordering, concurrency, or lifecycle.
- Record non-obvious design reasons, constraints, and trade-offs. Include an alternative only when its rejection explains the chosen design, and an unchanged boundary only when readers could otherwise infer a broader change.
- Keep the essential reasoning self-contained. Use links, issue IDs, and commit references as supporting context, not substitutes for the explanation.
- Describe the final change. Remove author narration, review chronology, file or function inventories, mechanical restatement of code, and repetition of the subject.
- Add verification when it helps assess the change: actual command or method, result, and relevant environment. Never claim tests, integration, deployment, or migration that did not occur; state a material verification gap when it limits the claim.
- Use short paragraphs and bullets for distinct consequences. Do not require a fixed set of headings. Wrap prose near 72 columns; preserve exact commands and URLs.

## Add conditional details

- For performance claims, give a comparable baseline, workload, metric, environment, and measurement method. Without measurements, describe the mechanism without inventing speedups.
- For configuration changes, state old and new defaults, precedence, and treatment of existing values when affected.
- For data or deployment changes, state affected data, required order, rerun behavior, and rollback limits when relevant. Distinguish adding migration code from executing it.
- For security fixes, state the affected boundary and corrected check; link a public advisory when available. Do not include secrets or private incident details.
- Mark broken consumer contracts with `!` and explain the old contract, affected callers, and required migration in `BREAKING CHANGE:`. The specification permits either marker; using both is this skill's default. Urgency or a dependency's major version alone does not establish a breaking change.

## Commit forms and footers

- For a series, describe only what each commit completes. Do not claim later integration in a preparatory commit.
- For squash commits, rewrite from the final combined diff; discard WIP notes and intermediate attempts while preserving required attribution.
- For merge commits, retain the repository's merge format and explain meaningful conflict-resolution choices.
- For backports, retain the original purpose and record the source SHA, target branch differences, and verification on that target.
- For reverts, identify the original SHA, reason, full or partial reversal, and restored behavior.
- Use `chore(release)` for actual release metadata changes. Do not imply publication from a version edit. Treat Git tags and autosquash prefixes separately from ordinary message prefixes.
- Put footers after a blank line. Use `Refs:` for related work and `Closes:` only for completed work; respect the hosting service's closing rules.
- Preserve the repository's source-commit tracking format; if none exists, use `Original-Commit:` for backports.
- Add `Co-authored-by:`, `Reviewed-by:`, and `Tested-by:` only from actual contribution or confirmation. Put test commands in the body, not `Tested-by:`.
- Use `Signed-off-by:` only under the project's contribution policy; do not treat it as review approval or a cryptographic signature.

## Commit messages: always use a heredoc (`-F -`)

For every commit message — single-line or multi-paragraph — pipe the whole message through `git commit -F -` (heredoc), or `-F <file>`. This gives full control over wrapping: wrap prose at ~72 columns *within* a paragraph, and put a single blank line only *between* paragraphs (and after the subject).

```bash
git commit -F - <<'EOF'
fix(scope): Imperative summary of the corrected behavior

Start with the problem or need and the condition under which it matters,
then how the change addresses it and any non-obvious decision — these
lines flow together because they are one paragraph, not separate flags.

- bullets are fine for distinct consequences; keep the body tight

Refs: #123
EOF
```

Never build a commit message from `-m` flags — not even a single-line one. git turns each `-m` into its own paragraph with a blank line between, so a body split across several `-m` flags becomes disconnected half-sentences. The heredoc form above is the only form to use.

## Common rationalizations

| Rationalization | Reality |
|---|---|
| "`git add -A` is faster and the tree is clean anyway" | You checked the tree you expected, not the one that's there. Stage by path; it costs seconds. |
| "The user said commit earlier, so this one is fine too" | Each commit needs its own request. An earlier "commit" covered that change. |
| "It's a one-line message, `-m` is fine" | `-m` habits split bodies into broken paragraphs later. Use the heredoc every time. |
| "I'll write the message from what I meant to change" | The message describes the staged diff. If they disagree, fix the staging. |
| "It's only my own unpushed commit, amending is harmless" | Amending after a failed hook can lose work. Make a new commit unless the user asked for an amend. |

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
