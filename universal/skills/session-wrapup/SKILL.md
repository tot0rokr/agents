---
name: session-wrapup
description: Close out the current agent session when the user asks to wrap up - account for this session's own work (committed, pushed, or still pending), stop what it left running, delete only the temporary files and test containers this session created, record the session if a logging skill exists, and report what is done, left open, and kept on purpose. Use at the end of a long or multi-step session, or when the user asks to clean up what the session left behind. Skip when the user only wants a session log written (use the logging skill directly) or wants files from another session cleaned up. Korean triggers include "wrap up해", "마무리해", "세션 정리해", "세션 정리하고 끝내자", "작업하던 더미 지워", "임시 파일 지우고 끝내자", "이 세션에서 할 거 끝났나".
---

# Session wrap-up

Work through the steps in order. Collect everything that needs the user's approval and ask once, rather than asking at every step.

## 1. Account for this session's work

- List every repository and directory this session touched: what it edited, created, cloned, installed or committed. Build the list from the session itself (files you edited, commands you ran, commits you made), not from whatever happens to be dirty now.
- In each repository check `git status --short`, unpushed commits (`git log origin/<branch>..HEAD`), stashes, and worktrees or branches the session added.
- Label every pending item: this session's, another session's or the user's, or unsure. Count an item as this session's only on direct evidence: you edited that path in this session, you made that commit (you saw its hash), or the file appeared from your command. Another session can edit and commit in the same repositories at the same time, so modification times and commit authorship alone prove nothing.
- Do not commit or push in this step. List what is pending and ask. Never stage another session's changes.

## 2. Stop what this session left running

- Background shell tasks, subagents, monitors, scheduled wake-ups and servers this session started: stop them or wait for them. If one has to keep running, say which and why.
- Test containers, volumes, networks and images this session created (find them by the names or labels it used, e.g. `claude-test-*`): remove them. Never stop or remove a container this session did not create.
- Temporary worktrees and branches: if merged and clean, remove them (`git worktree remove`, `git branch -d`); otherwise ask.

## 3. Delete this session's temporary files

- Candidates: the session scratchpad, logs this session wrote under `/tmp/$USER`, downloaded clones and archives, test fixtures.
- List each target with its size before deleting anything, then delete by exact path. No globs that could reach files this session did not create.
- A forked or resumed session can reuse the same scratchpad path. Delete only entries you recognize as this session's; leave the rest and say so.
- Keep, and only mention: backups (`*.bak.*`, `.backup-*`), anything the user said to keep, and things installed on purpose (packages, plugins, clones kept for further work).
- The user asking to wrap up approves deleting this session's own temporary files. It approves nothing else; for anything more, follow critical-file-safety and ask.

## 4. Record

- If a session-log skill is installed (for example `wrap-up`), run it. Otherwise skip unless the user asks. The log goes where that skill puts it, never into a tracked public repository.
- If the session produced a durable lesson (a correction from the user, a non-obvious fact about the environment), propose a memory entry. Write it only after the user agrees.

## 5. Report

Keep it short, in this order:

1. Done: work this session finished, with commit hashes and where they were pushed.
2. Not done: requests left open, and why.
3. Kept on purpose: backups, installs, working copies, with paths.
4. Not this session's: pending changes from other sessions that were found and left alone.
5. Deleted: what was removed.

Ending the session is the user's action. Do not say the session has ended.

## Common rationalizations

| Rationalization | Reality |
|---|---|
| "The repo is dirty, so I'll commit everything to leave it clean." | Other sessions work in the same repositories. Commit only this session's changes, and only when asked. |
| "It's in my scratchpad, so it's mine." | A forked or resumed session can share the path. Check what is in it. |
| "Everything under /tmp/$USER is temporary." | The user and other sessions write there too. Delete by exact name. |
| "The backup isn't needed any more." | Backups are the user's safety net. The user decides when they go. |
| "Nothing is pending." | Say so only after checking status and unpushed commits in every repository this session touched. |

## Verification

- Every repository this session touched was checked, and each pending item is labeled.
- `docker ps -a` lists none of this session's test containers; background work is stopped or reported.
- Each deleted path was listed before it was deleted, and nothing outside this session's own artifacts was removed.
