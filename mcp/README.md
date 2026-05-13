# integrated-harness-kit-mcp

An MCP server that exposes diagnostic and (in later versions) management
tools for the [`tot0rokr/agents`](https://github.com/tot0rokr/agents)
harness — the shared configuration layer for **Claude Code**, **Codex
CLI**, **OpenCode**, and **Gemini CLI**.

## Install

```bash
uvx integrated-harness-kit-mcp
```

That command runs the server on stdio; pair it with a CLI agent's MCP
client (see the repo root's `INSTALLATION.md` for ready-made config
snippets per CLI).

## What's available

### v0.2 — read-only

| Tool | Purpose |
|---|---|
| `harness_status` | repo presence + state of the 5 home-dir symlinks |
| `doctor` | run the harness's `scripts/doctor.sh` and surface its output |
| `list_skills` | enumerate registered SKILL.md entries |
| `list_mcp_servers` | enumerate canonical MCP servers in `shared/mcp/servers.json` |
| `list_commands` | enumerate slash commands in `shared/commands/` |
| `list_subagents` | enumerate sub-agents in `shared/subagents/` |

### Planned

- **v0.3** — `clone`, `install`, `render` (mutate the harness from inside a chat)
- **v0.4** — `add_skill`, `add_mcp_server`, `add_command`, `add_subagent` (+ `remove_*`)
- **v0.5** — `update`, `audit_drift`, `commit`, `edit_memory`, `edit_instruction`

## Repo discovery

Every tool resolves the agents repo in this order:

1. The function's `repo_path` argument.
2. The `AGENTS_REPO` environment variable.
3. `~/agents`.

A candidate is accepted only if it contains `scripts/install.py`.

## Development

```bash
cd mcp/
python3 -m venv .venv
.venv/bin/pip install -e '.'
.venv/bin/python -m unittest discover -s tests -v
```

Tools live in `src/integrated_harness_kit_mcp/tools/` as plain functions, so the
unit tests don't import `mcp` and don't depend on FastMCP behaviour.

## License

MIT. See repo root.
