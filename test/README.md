# Fresh-environment test container

A throwaway Ubuntu container with just enough installed to replay the
`INSTALLATION.md` bootstrap flow as if this were the first time anyone
had touched this machine. No host volumes are mounted, no host config
leaks in.

## Build

From the repo root:

```bash
docker build -t agents-test -f test/Dockerfile .
```

## Run

```bash
docker run -it --rm agents-test
```

Drops you into a `bash` shell as user `agent` with `$HOME=/home/agent`.
`python3`, `git`, `uvx`, `jq`, `rsync` are on PATH.

## Suggested walkthrough

Inside the container — exactly what INSTALLATION.md tells an agent to do:

```bash
# 1. Clone
git clone https://github.com/tot0rokr/agents.git ~/agents

# 2. Install (Python rewrite of install.sh, with auto-rollback)
python3 ~/agents/scripts/install.py

# 3. Verify
bash ~/agents/scripts/doctor.sh

# 4. Check what got linked
ls -la ~/.claude ~/.codex ~/.config/opencode ~/.gemini ~/.agents

# 5. Try the MCP server locally (PyPI version)
uvx integrated-harness-kit-mcp &
sleep 1
kill %1
```

Each step should succeed cleanly. Step 2 backs up nothing (fresh home),
Step 3 should print `doctor: all checks passed`, Step 4 should show five
symlinks under `~/agents/`, Step 5 should print nothing (server is on
stdio, exits silently when killed).

## Notes on what the container does *not* include

- No CLI agent (no Claude Code, no Codex CLI, etc.). The walkthrough is
  a manual replay of what INSTALLATION.md would have an agent do.
- No PyPI credentials. The container can install released packages but
  not publish.
- No SSH keys, no git identity. If you want to commit from inside, set
  them up by hand.

## Cleanup

```bash
# After exit, the container is gone (--rm). To remove the image:
docker rmi agents-test
```
