"""Agent-side MCP dispatch tests.

These exercise the routing decision in `StepAgent._execute_native`: an MCP tool
name (member of the manager's namespaced `tool_names`) goes to `call_tool`; any
other name falls through to native dispatch with no MCP round-trip and no
result-string sniffing (the v0.14 `"error:"`-sniffing regression).

`test_mcp_agent_wiring_parity` drives the same attach path the TUI uses — build
the manager, start it, attach to the agent — and asserts the observable
post-conditions (`name ∈ dispatch set` and present in `_tool_schemas()`).
"""

from __future__ import annotations

from contextlib import AsyncExitStack
from pathlib import Path

from mcp import ClientSession
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session

from code_scalpel.agent import StepAgent
from code_scalpel.config import AgentConfig, AppConfig, ModelProfile
from code_scalpel.llm.adapter import NativeToolCall
from code_scalpel.mcp_client import McpCallOutcome, McpManager, SessionOpener
from tests.mocks import MockLLMAdapter

_CONFIG = AppConfig(
    profiles={"local": ModelProfile(provider="lmstudio", model="m", temperature=0.1)},
    agent=AgentConfig(enforce_read_before_show=False),
)


def _opener_for(server: FastMCP) -> SessionOpener:
    async def opener(stack: AsyncExitStack) -> ClientSession:
        session: ClientSession = await stack.enter_async_context(
            create_connected_server_and_client_session(server)
        )
        await session.initialize()
        return session

    return opener


def _write_config(tmp_path: Path, names: list[str]) -> None:
    cfg_dir = tmp_path / ".code-scalpel"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    import json

    payload = {"mcpServers": {n: {"command": "ignored"} for n in names}}
    (cfg_dir / "mcp.json").write_text(json.dumps(payload))


def _agent(tmp_path: Path) -> StepAgent:
    return StepAgent(llm=MockLLMAdapter([""]), cwd=tmp_path, config=_CONFIG)


# ── manager doubles ─────────────────────────────────────────────────────────


class _SpyManager:
    """A minimal stand-in matching the surface `_execute_native` touches:
    `tool_names` and `async call_tool`. Records calls so we can assert the MCP
    path was (or wasn't) taken."""

    def __init__(self, names: set[str], outcome: McpCallOutcome) -> None:
        self._names = names
        self._outcome = outcome
        self.calls: list[tuple[str, dict]] = []

    @property
    def tool_names(self) -> set[str]:
        return self._names

    async def call_tool(self, name: str, args: dict) -> McpCallOutcome:
        self.calls.append((name, args))
        return self._outcome


# ── dispatch by name ────────────────────────────────────────────────────────


async def test_agent_dispatches_mcp_tool_by_name(tmp_path: Path) -> None:
    spy = _SpyManager({"srv.do"}, McpCallOutcome(ok=True, output="mcp-output"))
    agent = _agent(tmp_path)
    agent._mcp = spy

    result = await agent._execute_native(
        NativeToolCall(id="1", name="srv.do", arguments='{"x": 1}')
    )
    assert result.ok is True
    assert result.output == "mcp-output"
    assert spy.calls == [("srv.do", {"x": 1})]


async def test_agent_mcp_isError_routes_to_ok_false(tmp_path: Path) -> None:
    spy = _SpyManager({"srv.do"}, McpCallOutcome(ok=False, output="boom"))
    agent = _agent(tmp_path)
    agent._mcp = spy

    result = await agent._execute_native(NativeToolCall(id="1", name="srv.do", arguments="{}"))
    assert result.ok is False
    assert result.output == "boom"


async def test_agent_native_tool_not_intercepted_by_mcp(tmp_path: Path) -> None:
    # Regression for the v0.14 "error:"-sniffing bug: a native tool whose
    # output legitimately starts with "error:" must route native and never hit
    # the MCP manager. We write a file whose content is `error: ...`; read_file
    # returns it with ok=True. The manager exposes no `read_file` name, so the
    # name-membership gate keeps it on the native path — and call_tool is never
    # invoked.
    (tmp_path / "note.txt").write_text("error: this is real file content\n")
    spy = _SpyManager({"srv.do"}, McpCallOutcome(ok=False, output="should-not-be-used"))
    agent = _agent(tmp_path)
    agent._mcp = spy

    result = await agent._execute_native(
        NativeToolCall(id="1", name="read_file", arguments='{"path": "note.txt"}')
    )
    assert result.ok is True
    assert "error: this is real file content" in result.output
    assert spy.calls == []  # native path taken — no MCP round-trip


async def test_collision_native_vs_mcp_dispatch(tmp_path: Path) -> None:
    # A manager that (wrongly) claims a native name in tool_names would shadow
    # the native tool. The real manager excludes native names, so a correctly
    # built manager never lists `read_file`; here we assert dispatch keys on the
    # manager's set, and the real manager's exclusion (tested in
    # test_mcp_native_tool_wins_on_collision) keeps native names out of it.
    # End-to-end: build a real manager whose server's bare tool collides with a
    # native name and verify the native tool still dispatches at call time.
    srv = FastMCP(name="fake")

    def write_file(path: str) -> str:  # collides with native bare name
        return "mcp-write"

    srv.add_tool(write_file, name="write_file")
    _write_config(tmp_path, ["core"])
    agent = _agent(tmp_path)
    mgr = McpManager(
        tmp_path,
        native_tool_names=agent.native_tool_names(),
        session_openers={"core": _opener_for(srv)},
    )
    await mgr.start()
    agent._mcp = mgr
    try:
        # The colliding MCP tool was dropped — native write_file is reachable
        # (it will fail validation without content, but it's the NATIVE tool,
        # proven by the error text shape, not the MCP "mcp-write").
        assert "core.write_file" not in mgr.tool_names
        result = await agent._execute_native(
            NativeToolCall(id="1", name="write_file", arguments='{"path": "x.txt"}')
        )
        assert "mcp-write" not in result.output  # native tool ran, not the MCP one
    finally:
        await mgr.close()


# ── interaction scenarios ───────────────────────────────────────────────────


async def test_first_turn_during_mcp_startup(tmp_path: Path) -> None:
    # A manager mid-initialization (started=False, no tools yet) attached to the
    # agent. A native tool call during this window must run fine; the empty
    # tool_names means no MCP interception.
    mgr = McpManager(tmp_path)  # no config → empty, simulates "nothing ready yet"
    agent = _agent(tmp_path)
    agent._mcp = mgr
    (tmp_path / "f.txt").write_text("hello\n")

    result = await agent._execute_native(
        NativeToolCall(id="1", name="read_file", arguments='{"path": "f.txt"}')
    )
    assert result.ok is True
    assert "hello" in result.output


async def test_reload_during_active_turn(tmp_path: Path) -> None:
    # Defined behavior: reload tears down + reconnects; an MCP call issued after
    # reload routes to the fresh connection. We start, issue a call, reload, and
    # issue another — both succeed with no corruption (the worker-per-server
    # model gives each connection an isolated lifetime).
    srv = FastMCP(name="fake")

    def ping() -> str:
        return "pong"

    srv.add_tool(ping, name="ping")
    _write_config(tmp_path, ["s1"])
    mgr = McpManager(tmp_path, session_openers={"s1": _opener_for(srv)})
    await mgr.start()
    try:
        first = await mgr.call_tool("s1.ping", {})
        assert first.output == "pong"
        await mgr.reload()
        second = await mgr.call_tool("s1.ping", {})
        assert second.output == "pong"
    finally:
        await mgr.close()


# ── wiring parity (same attach path the TUI uses) ───────────────────────────


async def test_mcp_agent_wiring_parity(tmp_path: Path) -> None:
    # Drive the TUI's attach sequence: build manager → start → attach to agent.
    # Then assert the observable post-conditions: the namespaced tool name is in
    # the agent's dispatch set AND present in _tool_schemas().
    srv = FastMCP(name="fake")

    def echo(text: str) -> str:
        return f"echo:{text}"

    srv.add_tool(echo, name="echo")
    _write_config(tmp_path, ["s1"])

    agent = _agent(tmp_path)
    manager = McpManager(
        tmp_path,
        tool_timeout=_CONFIG.agent.mcp_tool_timeout,
        native_tool_names=agent.native_tool_names(),
        session_openers={"s1": _opener_for(srv)},
    )
    await manager.start()
    agent._mcp = manager  # same attach the TUI's _init_mcp performs
    try:
        # In the dispatch set the agent keys on.
        assert "s1.echo" in agent._mcp.tool_names
        # In the schema list the model sees.
        schema_names = {s["function"]["name"] for s in agent._tool_schemas()}
        assert "s1.echo" in schema_names
        # And actually dispatches end-to-end through _execute_native.
        result = await agent._execute_native(
            NativeToolCall(id="1", name="s1.echo", arguments='{"text": "wired"}')
        )
        assert result.ok is True
        assert result.output == "echo:wired"
    finally:
        await manager.close()
