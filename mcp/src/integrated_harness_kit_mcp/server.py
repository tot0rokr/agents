"""FastMCP entry point for integrated-harness-kit-mcp.

The tool functions live in `tools/` as plain callables so they can be
unit-tested without the `mcp` library installed. This module wraps them
with FastMCP and exposes the `main()` console-script entry point.
"""

from __future__ import annotations

try:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _McpServer
except ModuleNotFoundError:  # mcp 2.x renamed FastMCP to MCPServer
    from mcp.server.mcpserver import MCPServer as _McpServer

from .tools.bootstrap import bootstrap
from .tools.content import remove_content, scaffold
from .tools.listing import list_content, list_mcp_servers
from .tools.maintenance import audit_drift, commit, update
from .tools.mcp_servers import mcp_server_remove, mcp_server_set
from .tools.overlay import (
    overlay_add,
    overlay_commit,
    overlay_install,
    overlay_list,
    overlay_remove,
    overlay_route,
    overlay_setup,
)
from .tools.render import render
from .tools.settings import settings_get, settings_set
from .tools.status import capabilities, status

mcp = _McpServer("integrated-harness-kit")

# Diagnostics.
mcp.tool()(status)
mcp.tool()(capabilities)
mcp.tool()(audit_drift)

# What the harness offers.
mcp.tool()(list_content)
mcp.tool()(list_mcp_servers)
mcp.tool()(overlay_list)
mcp.tool()(overlay_route)
mcp.tool()(settings_get)

# Change it.
mcp.tool()(scaffold)
mcp.tool()(remove_content)
mcp.tool()(settings_set)
mcp.tool()(mcp_server_set)
mcp.tool()(mcp_server_remove)

# Lifecycle.
mcp.tool()(bootstrap)
mcp.tool()(update)
mcp.tool()(render)
mcp.tool()(overlay_add)
mcp.tool()(overlay_install)
mcp.tool()(overlay_remove)
mcp.tool()(overlay_setup)

# Committing.
mcp.tool()(commit)
mcp.tool()(overlay_commit)


def main() -> None:
    """Console-script entry: `integrated-harness-kit-mcp` (stdio transport)."""
    mcp.run()


if __name__ == "__main__":
    main()
