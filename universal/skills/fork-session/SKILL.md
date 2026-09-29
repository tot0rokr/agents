---
name: fork-session
description: Fork the running Claude Code session into a new tmux window so the user can talk to a copy that knows the whole conversation while the original keeps working. Use when the user asks to clone, fork, duplicate or branch this session or conversation into tmux, or wants to ask a side question without disturbing the running task. Trigger phrases include "세션 복제", "세션 복제해줘", "대화 복제해서 새 창", "이 세션 fork", "브랜치해서 tmux로 열어줘", "작업 중에 따로 물어보고 싶어", "fork this session", "clone the session", "branch this conversation into tmux", "open a copy of this chat". Skip when the user only wants /branch inside the same window, or wants to resume an old finished session.
---

# Fork this session into tmux

Run the bundled script. It finds this session in Claude Code's live-session registry, forks it with the native `claude --resume <id> --fork-session` (a new session id carrying the whole conversation), starts it the same way this session was started (same wrapper such as `claude-auto`, same `--plugin-dir`/`--settings`/`--model`/`--permission-mode` flags, same working directory), and opens it in a new tmux window right after this one. The original session is not touched and keeps running.

```bash
bash ~/.claude/skills/fork-session/fork-session.sh
```

- `--split` opens it as a pane beside this one instead of a new window.
- `--name NAME` names the fork (default: this session's name plus `-fork`); the name shows in the prompt box, the terminal title and `/resume`.
- `--dry-run` prints the command without starting anything.

After it runs, tell the user where the fork is (the script prints the tmux window, pane and new session id) and that they can switch to it and ask anything there; this session carries on with its task. Do not type into the fork yourself.

The fork starts from the conversation as it stands at that moment, including the turn in progress, so the user's first question there should say what they want to know rather than rely on the fork finishing the current task.

Outside tmux the script prints the command to run in a new terminal instead; pass that on to the user.

## Forking a busy session without asking it

A session that is busy cannot run a skill until its turn ends, so the script also takes a pane: `--pane %N` forks the Claude session running in that tmux pane. Suggest this binding if the user wants to fork from any pane with a key (prefix + F), without waiting for the session:

```tmux
bind-key F run-shell "bash ~/.claude/skills/fork-session/fork-session.sh --pane '#{pane_id}'"
```

Add it to the user's tmux config only if they ask.
