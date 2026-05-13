"""FastMCP entry point for harness-adapter-mcp.

The tool functions live in `tools/` as plain callables so they can be
unit-tested without the `mcp` library installed. This module wraps them
with FastMCP and exposes the `main()` console-script entry point.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .tools.clone import clone
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

mcp = FastMCP("harness-adapter")

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


def main() -> None:
    """Console-script entry: `harness-adapter-mcp` (stdio transport)."""
    mcp.run()


if __name__ == "__main__":
    main()
