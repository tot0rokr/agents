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

## Automated runs

Two scripts drive the container without a human in it.

`e2e_v1.py` plays out what someone with a new laptop does — bootstrap the harness, add a private overlay from a local "internal" repo, change settings, add MCP servers, render every scope, route a path, scaffold content, run the overlay's setup steps, commit — and asserts the result on disk rather than trusting what the tools reported. It ends by scanning every tracked file for the overlay's credentials and hostname, which are generated fresh each run so no fixture string can satisfy or trip the check.

```bash
docker build -t agents-test -f test/Dockerfile .
docker run --rm -v "$PWD:/src:ro" agents-test bash -lc '
  git config --global user.name agent && git config --global user.email agent@test
  cp -r /src /home/agent/source
  cd /home/agent/source && rm -f .git && git init -q -b main && git add -A && git commit -qm snapshot
  python3 /home/agent/source/test/e2e_v1.py'
```

`qa_v1.py` is the adversarial pass: path traversal through every name and path argument, corrupt and truncated state files, a registered overlay whose clone has been moved away, unwritable targets, an overlay whose `links` map points outside the repo, proof that setup steps never run except through `overlay_setup(yes=True)`, priority conflicts, idempotence, complete removal, a pre-overlay repo, unicode, and a repo with no `.git`. A tool is allowed to return an error; it is never allowed to raise.

Each script bootstraps into `$HOME`, so give each one its own `docker run` — two in the same container fight over the home symlinks.

`e2e_mcp_protocol.py` speaks MCP over stdio to the installed server: initialize, `tools/list`, then real calls. The unit tests import the tool functions directly and never load `mcp`, so this is the only place a registration or schema problem shows up — and where a dependency that no longer exists under that name would. Run it against both majors:

```bash
for spec in "mcp<2" "mcp>=2"; do
  uv venv -q /home/agent/venv && uv pip install -q --python /home/agent/venv/bin/python /home/agent/source/mcp "$spec"
  MCP_SERVER_CMD=/home/agent/venv/bin/integrated-harness-kit-mcp \
    /home/agent/venv/bin/python /home/agent/source/test/e2e_mcp_protocol.py /home/agent/agents
  rm -rf /home/agent/venv
done
```

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
