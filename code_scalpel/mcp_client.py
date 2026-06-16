"""MCP (Model Context Protocol) client — subprocess + JSON-RPC over stdio.

Language-agnostic: MCP servers can be written in any language.
One integration unlocks browser, filesystem, database, and more.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from pathlib import Path
from typing import Any


class McpTool:
    """A tool exposed by an MCP server, translated to OpenAI function-calling format."""
    def __init__(self, server_name: str, raw: dict[str, Any]) -> None:
        self.server_name = server_name
        self.name = raw.get("name", "")
        self.description = raw.get("description", "")
        self.input_schema: dict[str, Any] = raw.get("inputSchema", {})

    def to_openai_schema(self) -> dict[str, Any]:
        schema: dict[str, Any] = {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }
        if "type" not in schema["function"]["parameters"]:
            schema["function"]["parameters"]["type"] = "object"
        return schema


class McpServer:
    """One MCP server — managed via subprocess + JSON-RPC on stdio."""

    def __init__(self, name: str, command: str, args: list[str], env: dict[str, str] | None = None):
        self.name = name
        self.command = command
        self.args = args
        self.env = env
        self._proc: Any = None
        self._rid: int = 0
        self._tools: list[McpTool] = []

    async def _rpc(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._rid += 1
        msg = {"jsonrpc": "2.0", "id": self._rid, "method": method}
        if params:
            msg["params"] = params
        line = (json.dumps(msg) + "\n").encode()
        self._proc.stdin.write(line)
        await self._proc.stdin.drain()
        resp_line = await self._proc.stdout.readline()
        return json.loads(resp_line.decode().strip())

    async def start(self) -> None:
        env = os.environ.copy()
        if self.env:
            env.update(self.env)
        self._proc = await asyncio.create_subprocess_exec(
            self.command, *self.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        await self._rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "code-scalpel", "version": "1.0"},
        })
        # Notify initialized
        self._proc.stdin.write(b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
        await self._proc.stdin.drain()

    async def list_tools(self) -> list[McpTool]:
        if self._proc is None:
            return []
        result = await self._rpc("tools/list")
        raw = result.get("result", {}).get("tools", [])
        self._tools = [McpTool(self.name, t) for t in raw]
        return self._tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        if self._proc is None:
            return "error: server not connected"
        result = await self._rpc("tools/call", {"name": name, "arguments": arguments})
        contents = result.get("result", {}).get("content", [])
        parts = [c.get("text", "") for c in contents if isinstance(c, dict)]
        return "\n".join(parts) if parts else json.dumps(result)

    async def close(self) -> None:
        if self._proc is not None:
            with contextlib.suppress(Exception):
                self._proc.stdin.close()
                self._proc.terminate()
                await self._proc.wait()
            self._proc = None


class McpManager:
    """Manages all MCP server connections for one agent session."""

    def __init__(self, project_root: Path) -> None:
        self._servers: dict[str, McpServer] = {}
        self._tools: list[McpTool] = []
        self._started = False

        config = self._load_config(project_root)
        for name, cfg in config.get("servers", {}).items():
            self._servers[name] = McpServer(
                name=name,
                command=cfg["command"],
                args=cfg.get("args", []),
                env=cfg.get("env"),
            )

    @staticmethod
    def _load_config(project_root: Path) -> dict[str, Any]:
        for loc in [
            project_root / ".code-scalpel" / "mcp.json",
            Path.home() / ".config" / "code-scalpel" / "mcp.json",
        ]:
            if loc.exists():
                try:
                    return json.loads(loc.read_text())
                except (json.JSONDecodeError, OSError):
                    pass
        return {}

    async def start(self) -> list[McpTool]:
        if self._started:
            return list(self._tools)
        self._started = True
        for server in self._servers.values():
            try:
                await server.start()
                tools = await server.list_tools()
                self._tools.extend(tools)
            except Exception:
                pass
        return list(self._tools)

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        return [t.to_openai_schema() for t in self._tools]

    def find_server(self, tool_name: str) -> McpServer | None:
        for server in self._servers.values():
            for tool in server._tools:
                if tool.name == tool_name:
                    return server
        return None

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        server = self.find_server(tool_name)
        if server is None:
            return f"error: no MCP server for '{tool_name}'"
        return await server.call_tool(tool_name, arguments)

    async def close(self) -> None:
        for server in self._servers.values():
            await server.close()
        self._started = False
