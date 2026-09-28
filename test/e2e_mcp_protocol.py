#!/usr/bin/env python3
"""Drive the installed MCP server over stdio, the way a CLI agent does.

The unit tests import the tool functions directly and never load `mcp`, so
nothing there would catch a signature FastMCP cannot turn into a schema, or a
tool that fails to register. This speaks the protocol: initialize, list the
tools, call a few, and check what comes back.

Run inside the container after installing the package:

    python3 test/e2e_mcp_protocol.py <repo_path>
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

EXPECTED_TOOLS = {
    "status",
    "capabilities",
    "audit_drift",
    "list_content",
    "list_mcp_servers",
    "overlay_list",
    "overlay_route",
    "settings_get",
    "scaffold",
    "remove_content",
    "settings_set",
    "mcp_server_set",
    "mcp_server_remove",
    "bootstrap",
    "update",
    "render",
    "overlay_add",
    "overlay_install",
    "overlay_remove",
    "overlay_setup",
    "commit",
    "overlay_commit",
}

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    (PASSED if condition else FAILED).append(name)
    print(f"  [{'PASS' if condition else 'FAIL'}] {name}" + (f" — {detail}" if detail and not condition else ""))


class Server:
    """Minimal newline-delimited JSON-RPC client for one stdio MCP server."""

    def __init__(self, command: list[str]) -> None:
        self.proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._id = 0

    def request(self, method: str, params: dict | None = None, timeout: float = 30.0) -> dict:
        self._id += 1
        self._send({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}})
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError(f"server closed: {self.proc.stderr.read()[-2000:]}")
            message = json.loads(line)
            if message.get("id") == self._id:
                return message

    def notify(self, method: str, params: dict | None = None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def _send(self, payload: dict) -> None:
        self.proc.stdin.write(json.dumps(payload) + "\n")
        self.proc.stdin.flush()

    def close(self) -> None:
        self.proc.stdin.close()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def tool_payload(response: dict) -> dict:
    """Unwrap the tool result — FastMCP returns content blocks."""
    result = response.get("result", {})
    if "structuredContent" in result:
        return result["structuredContent"]
    for block in result.get("content", []):
        if block.get("type") == "text":
            try:
                return json.loads(block["text"])
            except json.JSONDecodeError:
                return {"text": block["text"]}
    return result


def main(repo_path: str) -> int:
    command = [os.environ.get("MCP_SERVER_CMD", "integrated-harness-kit-mcp")]
    print(f"== starting {command[0]}")
    server = Server(command)

    try:
        init = server.request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "e2e", "version": "1"},
            },
        )
        check("initialize succeeded", "result" in init, json.dumps(init)[:300])
        server_name = init.get("result", {}).get("serverInfo", {}).get("name", "")
        check("server identifies itself", server_name == "integrated-harness-kit", server_name)
        server.notify("notifications/initialized")

        listed = server.request("tools/list")
        tools = {tool["name"] for tool in listed.get("result", {}).get("tools", [])}
        missing = sorted(EXPECTED_TOOLS - tools)
        unexpected = sorted(tools - EXPECTED_TOOLS)
        check("every tool registered", not missing, f"missing: {missing}")
        check("no stale tools left behind", not unexpected, f"unexpected: {unexpected}")
        check("tool count is the pruned set", len(tools) == len(EXPECTED_TOOLS), str(len(tools)))

        schemas = {
            tool["name"]: tool.get("inputSchema", {})
            for tool in listed.get("result", {}).get("tools", [])
        }
        check(
            "schemas were generated for every tool",
            all(schema.get("type") == "object" for schema in schemas.values()),
            str([n for n, s in schemas.items() if s.get("type") != "object"]),
        )
        check(
            "descriptions survive into the schema",
            all(tool.get("description") for tool in listed.get("result", {}).get("tools", [])),
        )

        caps = tool_payload(server.request("tools/call", {"name": "capabilities", "arguments": {"repo_path": repo_path}}))
        check("capabilities over the protocol", caps.get("overlays") is True, json.dumps(caps)[:300])
        check("version reported as 1.0.0", caps.get("package_version") == "1.0.0", str(caps.get("package_version")))

        status = tool_payload(server.request("tools/call", {"name": "status", "arguments": {"repo_path": repo_path}}))
        check("status over the protocol", status.get("ok") is True, json.dumps(status)[:300])
        aliases = [o["alias"] for o in status.get("overlays", {}).get("installed", [])]
        check("overlay visible through the protocol", "work" in aliases, str(aliases))

        servers = tool_payload(
            server.request(
                "tools/call",
                {"name": "list_mcp_servers", "arguments": {"scope": "both", "repo_path": repo_path}},
            )
        )
        blob = json.dumps(servers)
        check("overlay-only server reported", servers.get("overlay_only") == ["internal-kb"], blob[:200])

        carrying_secrets = [
            entry["name"]
            for entry in servers.get("effective", [])
            if "env" in entry or "headers" in entry
        ]
        check("no server entry carries env or headers", not carrying_secrets, str(carrying_secrets))

        # The real values, read straight from the overlay, must not appear at all.
        overlay_servers = json.loads(
            (os.path.join(repo_path, "overlays/work/mcp/servers.json"))
            and open(os.path.join(repo_path, "overlays/work/mcp/servers.json")).read()
        )["servers"]
        secrets = [
            value
            for cfg in overlay_servers.values()
            for value in (cfg.get("env") or {}).values()
        ]
        check(
            "no credential value crosses the protocol",
            all(secret not in blob for secret in secrets),
            str([s for s in secrets if s in blob]),
        )
        check(
            "withholding is declared instead",
            any(entry.get("withheld") for entry in servers.get("effective", [])),
        )

        bad = server.request("tools/call", {"name": "list_content", "arguments": {"kind": "nope", "repo_path": repo_path}})
        payload = tool_payload(bad)
        check("a bad argument returns an error payload, not a crash", payload.get("ok") is False, json.dumps(payload)[:200])
    finally:
        server.close()

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        print("failed: " + ", ".join(FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/agents")))
