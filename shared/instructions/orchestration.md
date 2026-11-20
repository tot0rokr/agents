# Parallelism & orchestration

Default to parallelism for any work that has no sequential dependency. Serialize only genuine dependencies (e.g. read-before-edit, build-before-test). "Parallelize by default" means "when independent", not "always".

## Batch independent operations

- Issue independent tool calls (multiple file reads, greps, unrelated searches) together in a single turn so they run concurrently, instead of one at a time.
- Run long-lived commands (builds, test suites, dev servers, watchers) in the background. Act when the work reports completion — do not poll on a short timer, since polling wastes tokens and context/cache.
- Fan out independent workstreams (research, implementation, review) to parallel subagents.

## Concurrent code changes

- When two or more code tasks are independent and touch non-overlapping files/modules, do each in its own temporary git worktree (parent dir, named `project-branch`). When the background work has finished, report and leave the merge to the user: they decide when to merge, per [feedback_always_use_worktree](../memory/feedback_always_use_worktree.md). Merge right away only when the user explicitly said to.
- Worktree isolation only pays off at roughly 3+ files or an independent module. For one or two small edits the setup and merge overhead outweighs the benefit — just do it sequentially.
- If the tasks touch overlapping files, serialize them instead. Worktrees isolate the working tree; they do not remove merge conflicts.

## Partial failure

- If independent background tasks partially fail, keep the completed ones ready to merge, report the failures, then retry the failed ones. Do not abort the whole batch.
- If the tasks are interdependent, a failure means re-examining the related work as a group rather than merging piecemeal.

## After parallel work

- Parallel and subagent results are not shown to the user directly. After merging or completing, always summarize what was done and where.

## Teammates in tmux + worktrees (default when inside tmux)

When spawning a teammate (an interactive agent you converse with — see the feedback rule for when a teammate is warranted) and the session is running inside tmux, run each teammate in its own git worktree and its own tmux window so the user can watch and attach to it live.

- Create the worktree per the worktree rule (`../project-branch`), then launch the teammate in a new tmux window pointed at it: `tmux new-window -d -n <name> -c <worktree-path> "claude '<task>'; exec bash"`.
- Peek at its output with `tmux capture-pane -t <session>:<name> -p`; send it input with `tmux send-keys -t <session>:<name> '<text>' Enter`. (For in-process subagents, use the harness message channel instead.)
- Close the windows once all teammates finish, and leave the worktrees for the user to merge when they choose (right away only when told). Each teammate is a full independent session that consumes tokens, so close it when done.
- Only do this when the work warrants a teammate (needs feedback, or independent concurrent code work past the worktree threshold), and only when inside tmux — not for trivial one-shot lookups.
- Don't use the native `claude '<task>' --worktree <name> --tmux` setup: it creates the worktree under `.claude/worktrees/` instead of `../project-branch`, which breaks the worktree rule, and it hangs when invoked from a headless/background process. Use the `tmux new-window` method above with a worktree you created.

## Fanning out

- Before fanning out reviewers, check that each one produces a different kind of finding (correctness, security, performance, docs). Two reviewers with the same lens double the cost and the noise.
- For an intermittent failure with several plausible causes, give competing hypotheses to separate agents and converge when the evidence rules out the others, instead of one agent chasing the first idea.

## Multi-agent orchestration

- Large multi-agent orchestration (fanning out many agents to one goal) is opt-in only. Use it when the user explicitly asks for it in a given session — not by default.
