"""MCP (Model Context Protocol) client — connects to MCP servers and
exposes their tools as native scalpel tool calls.

Language-agnostic: MCP servers can be written in any language.
One integration unlocks browser (Playwright), filesystem, database,
and any other MCP-compatible tool.
"""

from __future__ import annotations

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
        """Convert to OpenAI function-calling schema."""
        schema: dict[str, Any] = {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }
        # OpenAI requires "type": "object" at the top level
        if "type" not in schema["function"]["parameters"]:
            schema["function"]["parameters"]["type"] = "object"
        return schema


class McpServer:
    """One MCP server connection — manages a subprocess via stdio."""

    def __init__(self, name: str, command: str, args: list[str], env: dict[str, str] | None = None):
        self.name = name
        self.command = command
        self.args = args
        self.env = env
        self._process: Any = None
        self._session: Any = None
        self._tools: list[McpTool] = []

    async def start(self) -> None:
        """Launch the MCP server subprocess and initialize the session."""
        env = os.environ.copy()
        if self.env:
            env.update(self.env)

        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        params = StdioServerParameters(
            command=self.command,
            args=self.args,
            env=env,
        )
        self._stdio_ctx = stdio_client(params)
        read_stream, write_stream = await self._stdio_ctx.__aenter__()
        self._session = ClientSession(read_stream, write_stream)
        await self._session.initialize()

    async def list_tools(self) -> list[McpTool]:
        """Fetch and cache the tool list from this server."""
        if self._session is None:
            return []

        result = await self._session.list_tools()
        self._tools = [
            McpTool(self.name, tool.model_dump() if hasattr(tool, "model_dump") else tool)
            for tool in result.tools
        ]
        return self._tools

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Execute a tool on this server and return the result text."""
        if self._session is None:
            return "error: MCP server not connected"

        result = await self._session.call_tool(tool_name, arguments)
        # Extract text content from the result
        contents = result.content if hasattr(result, "content") else []
        text_parts = []
        for c in contents:
            if hasattr(c, "text") or hasattr(c, "type") and c.type == "text":
                text_parts.append(c.text)
        return "\n".join(text_parts) if text_parts else str(result)

    async def close(self) -> None:
        """Shut down the server connection."""
        if self._session is not None:
            with contextlib.suppress(Exception):
                await self._session.__aexit__(None, None, None)
            self._session = None
        if hasattr(self, "_stdio_ctx") and self._stdio_ctx is not None:
            with contextlib.suppress(Exception):
                await self._stdio_ctx.__aexit__(None, None, None)
            self._stdio_ctx = None


class McpManager:
    """Manages all MCP server connections for one agent session.

    Config lives at `.code-scalpel/mcp.json` (per-project) or
    `~/.config/code-scalpel/mcp.json` (global).

    Example config:
    {
        "servers": {
            "playwright": {
                "command": "npx",
                "args": ["-y", "@playwright/mcp"],
                "env": {}
            }
        }
    }
    """

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
        """Load MCP config from project or global location."""
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
        """Start all configured servers and collect their tools."""
        if self._started:
            return list(self._tools)
        self._started = True

        for server in self._servers.values():
            try:
                await server.start()
                tools = await server.list_tools()
                self._tools.extend(tools)
            except Exception:
                # Server failed to start — skip it, agent still works
                pass

        return list(self._tools)

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        """All MCP tools as OpenAI function-calling schemas."""
        return [t.to_openai_schema() for t in self._tools]

    def find_server(self, tool_name: str) -> McpServer | None:
        """Find which server owns a tool by name."""
        for server in self._servers.values():
            for tool in server._tools:
                if tool.name == tool_name:
                    return server
        return None

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Dispatch a tool call to the correct server."""
        server = self.find_server(tool_name)
        if server is None:
            return f"error: no MCP server for tool '{tool_name}'"
        return await server.call_tool(tool_name, arguments)

    async def close(self) -> None:
        """Shut down all servers."""
        for server in self._servers.values():
            await server.close()
        self._started = False
