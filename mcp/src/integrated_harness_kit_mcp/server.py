"""FastMCP entry point for integrated-harness-kit-mcp.

The tool functions live in `tools/` as plain callables so they can be
unit-tested without the `mcp` library installed. This module wraps them
with FastMCP and exposes the `main()` console-script entry point.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .tools.clone import clone
from .tools.content import (
    add_command,
    add_mcp_server,
    add_skill,
    add_subagent,
    remove_command,
    remove_mcp_server,
    remove_skill,
    remove_subagent,
)
from .tools.doctor import doctor
from .tools.install_tool import install
from .tools.listing import (
    list_commands,
    list_mcp_servers,
    list_skills,
    list_subagents,
)
from .tools.render import render
from .tools.status import harness_status

mcp = FastMCP("integrated-harness-kit")

# Register every tool. FastMCP introspects the function signature and
# docstring to produce the MCP tool schema.

# Read-only / diagnostics.
mcp.tool()(harness_status)
mcp.tool()(doctor)
mcp.tool()(list_skills)
mcp.tool()(list_mcp_servers)
mcp.tool()(list_commands)
mcp.tool()(list_subagents)

# Mutate / lifecycle.
mcp.tool()(clone)
mcp.tool()(install)
mcp.tool()(render)

# Content add/remove (v0.4).
mcp.tool()(add_skill)
mcp.tool()(remove_skill)
mcp.tool()(add_mcp_server)
mcp.tool()(remove_mcp_server)
mcp.tool()(add_command)
mcp.tool()(remove_command)
mcp.tool()(add_subagent)
mcp.tool()(remove_subagent)


def main() -> None:
    """Console-script entry: `integrated-harness-kit-mcp` (stdio transport)."""
    mcp.run()


if __name__ == "__main__":
    main()
