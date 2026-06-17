"""Tests for the SDK-based MCP client (`code_scalpel.mcp_client`).

The fake in-memory MCP server is a real `FastMCP` driven through the SDK's
`create_connected_server_and_client_session` in-memory transport — so the
manager's worker/call/teardown path runs against a genuine `ClientSession`
producing genuine `CallToolResult` objects (the two-tier error model, the
content shape), not a hand-rolled dict mimic. The manager's `session_openers`
seam swaps the stdio/HTTP transport for this in-memory session while leaving
every other line of the connect/dispatch/teardown path identical.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

import pytest
from mcp import ClientSession
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import CallToolResult, TextContent

from code_scalpel.mcp_client import (
    McpManager,
    SessionOpener,
    _extract_text,
    _parse_config,
)

# ── fake in-memory server plumbing ──────────────────────────────────────────


def _make_server(name_to_fn: dict[str, Any]) -> FastMCP:
    """Build a FastMCP server exposing the given tools. A tool that raises
    surfaces as `isError=True` (FastMCP catches the exception); a tool that
    sleeps lets us exercise the per-call timeout."""
    srv = FastMCP(name="fake")
    for tool_name, fn in name_to_fn.items():
        srv.add_tool(fn, name=tool_name)
    return srv


def _opener_for(server: FastMCP) -> SessionOpener:
    """A session-opener that enters the in-memory server/client pair onto the
    manager's worker stack, matching the real opener's contract (enter into the
    given stack, return an initialized session)."""

    async def opener(stack: AsyncExitStack) -> ClientSession:
        session: ClientSession = await stack.enter_async_context(
            create_connected_server_and_client_session(server)
        )
        await session.initialize()
        return session

    return opener


def _write_config(tmp_path: Path, payload: dict[str, Any]) -> Path:
    cfg_dir = tmp_path / ".code-scalpel"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "mcp.json").write_text(json.dumps(payload))
    return tmp_path


# ── config parsing ──────────────────────────────────────────────────────────


def test_mcp_config_prefers_mcpServers_over_servers() -> None:
    raw = {
        "mcpServers": {"a": {"command": "x"}},
        "servers": {"b": {"command": "y"}},
    }
    parsed = _parse_config(raw)
    assert [c.name for c in parsed] == ["a"]
    assert parsed[0].command == "x"


def test_mcp_config_legacy_servers_key() -> None:
    raw = {"servers": {"legacy": {"command": "cmd", "args": ["--flag"]}}}
    parsed = _parse_config(raw)
    assert len(parsed) == 1
    assert parsed[0].name == "legacy"
    assert parsed[0].transport == "stdio"
    assert parsed[0].args == ["--flag"]


def test_mcp_transport_selected_by_fields() -> None:
    raw = {
        "mcpServers": {
            "local": {"command": "npx", "args": ["-y", "pkg"]},
            "remote": {"url": "https://h/mcp", "headers": {"X": "1"}},
            "neither": {"foo": "bar"},
            "both": {"command": "c", "url": "https://h"},
        }
    }
    parsed = {c.name: c for c in _parse_config(raw)}
    assert parsed["local"].transport == "stdio"
    assert parsed["remote"].transport == "http"
    assert parsed["remote"].url == "https://h/mcp"
    assert parsed["remote"].headers == {"X": "1"}
    # neither / both → per-server config error, not a crash, transport empty.
    assert parsed["neither"].transport == ""
    assert parsed["neither"].error is not None
    assert parsed["both"].transport == ""
    assert parsed["both"].error is not None


# ── result extraction (stack-spec) ──────────────────────────────────────────


def test_mcp_result_content_extraction() -> None:
    # Output is read from CallToolResult.content[].text per the SDK result
    # shape. Source: docs/stack-notes.md `### mcp` (MCP spec 2025-06-18).
    result = CallToolResult(
        content=[TextContent(type="text", text="line1"), TextContent(type="text", text="line2")],
        isError=False,
    )
    assert _extract_text(result) == "line1\nline2"


# ── manager: connect / list / call against a real in-memory session ─────────


async def _manager_with_servers(
    tmp_path: Path,
    servers: dict[str, FastMCP],
    *,
    tool_timeout: float = 5.0,
    native_tool_names: set[str] | None = None,
    config_payload: dict[str, Any] | None = None,
) -> McpManager:
    if config_payload is None:
        config_payload = {"mcpServers": {name: {"command": "ignored"} for name in servers}}
    _write_config(tmp_path, config_payload)
    openers = {name: _opener_for(srv) for name, srv in servers.items()}
    return McpManager(
        tmp_path,
        tool_timeout=tool_timeout,
        native_tool_names=native_tool_names,
        session_openers=openers,
    )


def _echo_tool(text: str) -> str:
    return f"echo:{text}"


async def test_mcp_call_tool_success(tmp_path: Path) -> None:
    srv = _make_server({"echo": _echo_tool})
    mgr = await _manager_with_servers(tmp_path, {"s1": srv})
    statuses = await mgr.start()
    try:
        assert any(s.connected and s.name == "s1" for s in statuses)
        assert "s1.echo" in mgr.tool_names
        outcome = await mgr.call_tool("s1.echo", {"text": "hi"})
        assert outcome.ok is True
        assert outcome.output == "echo:hi"
    finally:
        await mgr.close()


async def test_mcp_call_tool_maps_isError_to_ok_false(tmp_path: Path) -> None:
    def boom() -> str:
        raise ValueError("kaboom")

    srv = _make_server({"boom": boom})
    mgr = await _manager_with_servers(tmp_path, {"s1": srv})
    await mgr.start()
    try:
        outcome = await mgr.call_tool("s1.boom", {})
        assert outcome.ok is False
        assert "kaboom" in outcome.output
    finally:
        await mgr.close()


async def test_mcp_call_tool_timeout(tmp_path: Path) -> None:
    async def slow() -> str:
        await asyncio.sleep(5)
        return "done"

    srv = _make_server({"slow": slow})
    mgr = await _manager_with_servers(tmp_path, {"s1": srv}, tool_timeout=0.2)
    await mgr.start()
    try:
        outcome = await mgr.call_tool("s1.slow", {})
        assert outcome.ok is False
        assert "timed out" in outcome.output
    finally:
        await mgr.close()


async def test_mcp_namespacing_between_servers(tmp_path: Path) -> None:
    srv_a = _make_server({"run": _echo_tool})
    srv_b = _make_server({"run": _echo_tool})
    mgr = await _manager_with_servers(tmp_path, {"alpha": srv_a, "beta": srv_b})
    await mgr.start()
    try:
        assert "alpha.run" in mgr.tool_names
        assert "beta.run" in mgr.tool_names
        # Both reachable under distinct namespaced names.
        a = await mgr.call_tool("alpha.run", {"text": "A"})
        b = await mgr.call_tool("beta.run", {"text": "B"})
        assert a.output == "echo:A"
        assert b.output == "echo:B"
    finally:
        await mgr.close()


async def test_mcp_native_tool_wins_on_collision(tmp_path: Path) -> None:
    # A server named "read_file" exposing a bare tool "x" → namespaced
    # "read_file.x"; and a server whose namespaced name equals a native name.
    srv = _make_server({"write_file": _echo_tool})  # bare "write_file" collides
    mgr = await _manager_with_servers(
        tmp_path,
        {"core": srv},
        native_tool_names={"write_file", "read_file"},
    )
    await mgr.start()
    try:
        # The bare name collides with a native tool → dropped from the set.
        assert "core.write_file" not in mgr.tool_names
        assert mgr.tool_names == set()
    finally:
        await mgr.close()


async def test_mcp_start_reports_per_server_failure(tmp_path: Path) -> None:
    good = _make_server({"echo": _echo_tool})

    # A "broken" server whose opener raises on connect (mimics bad command /
    # unreachable url). Its config is valid (has command) so it reaches the
    # connect path and fails there.
    async def broken_opener(stack: AsyncExitStack) -> ClientSession:
        raise ConnectionError("server unreachable")

    _write_config(
        tmp_path,
        {"mcpServers": {"good": {"command": "x"}, "bad": {"command": "y"}}},
    )
    mgr = McpManager(
        tmp_path,
        session_openers={"good": _opener_for(good), "bad": broken_opener},
    )
    statuses = {s.name: s for s in await mgr.start()}
    try:
        assert statuses["good"].connected is True
        assert statuses["good"].tool_count == 1
        assert statuses["bad"].connected is False
        assert statuses["bad"].reason is not None
        assert "unreachable" in statuses["bad"].reason
        # The good server's tools still loaded — one bad server didn't abort.
        assert "good.echo" in mgr.tool_names
    finally:
        await mgr.close()


async def test_mcp_invalid_config_reported_not_crash(tmp_path: Path) -> None:
    _write_config(tmp_path, {"mcpServers": {"weird": {"nothing": True}}})
    mgr = McpManager(tmp_path)
    statuses = await mgr.start()
    try:
        assert len(statuses) == 1
        assert statuses[0].connected is False
        assert statuses[0].reason is not None
    finally:
        await mgr.close()


def test_mcp_malformed_tools_list_skips_bad_tool(tmp_path: Path) -> None:
    # A server returns one malformed (name-less) tool alongside a well-formed
    # one. _register_tools must skip the bad entry and keep the good one — a
    # single malformed tools/list entry never drops the rest.
    from code_scalpel.mcp_client import ServerConfig, _ServerConnection

    class _Bare:
        name = ""

    class _Good:
        name = "ok"
        description = "d"
        inputSchema: dict[str, Any] = {}

    cfg = ServerConfig(name="x", transport="stdio", command="c")
    conn = _ServerConnection(cfg)
    conn.tools = [_Bare(), _Good()]  # type: ignore[list-item]

    mgr = McpManager(tmp_path)
    mgr._register_tools(cfg, conn)
    assert "x.ok" in mgr.tool_names
    assert "x." not in mgr.tool_names  # the name-less one produced no entry


async def test_mcp_malformed_tools_list_via_real_path(tmp_path: Path) -> None:
    # Same intent, but confirming the well-formed tool loads through the real
    # connect path (the skip branch above is the malformed half).
    good = _make_server({"echo": _echo_tool})
    mgr = await _manager_with_servers(tmp_path, {"s1": good})
    await mgr.start()
    try:
        assert "s1.echo" in mgr.tool_names
    finally:
        await mgr.close()


async def test_mcp_tool_schemas_namespaced(tmp_path: Path) -> None:
    srv = _make_server({"echo": _echo_tool})
    mgr = await _manager_with_servers(tmp_path, {"s1": srv})
    await mgr.start()
    try:
        schemas = mgr.tool_schemas()
        names = {s["function"]["name"] for s in schemas}
        assert "s1.echo" in names
        # OpenAI function-format shape.
        echo_schema = next(s for s in schemas if s["function"]["name"] == "s1.echo")
        assert echo_schema["type"] == "function"
        assert echo_schema["function"]["parameters"]["type"] == "object"
    finally:
        await mgr.close()


async def test_mcp_reload_reconnects(tmp_path: Path) -> None:
    srv = _make_server({"echo": _echo_tool})
    mgr = await _manager_with_servers(tmp_path, {"s1": srv})
    await mgr.start()
    try:
        assert "s1.echo" in mgr.tool_names
        statuses = await mgr.reload()
        # After reload the same in-memory opener reconnects the server.
        assert any(s.connected for s in statuses)
        assert "s1.echo" in mgr.tool_names
        outcome = await mgr.call_tool("s1.echo", {"text": "again"})
        assert outcome.output == "echo:again"
    finally:
        await mgr.close()


async def test_mcp_no_config_is_noop(tmp_path: Path) -> None:
    mgr = McpManager(tmp_path)  # no mcp.json under tmp_path
    statuses = await mgr.start()
    assert statuses == []
    assert mgr.tool_names == set()
    assert mgr.tool_schemas() == []
    await mgr.close()


# ── stack-spec: streamable-HTTP 3-tuple ─────────────────────────────────────


async def test_mcp_streamable_http_handles_three_tuple(monkeypatch: pytest.MonkeyPatch) -> None:
    # The client must consume the (read, write, get_session_id) 3-tuple the SDK
    # yields for streamable-HTTP — unpacking as a 2-tuple raises. We verify the
    # real `_open_session` unpacks three values by feeding a fake streamable
    # client that yields a 3-tuple; a 2-tuple-only consumer would ValueError.
    # Source: docs/stack-notes.md `### mcp` (python-sdk v1.28.0 streamable_http.py).
    import code_scalpel.mcp_client as mc
    from code_scalpel.mcp_client import ServerConfig, _ServerConnection

    captured: dict[str, Any] = {}

    class _FakeStreamCtx:
        async def __aenter__(self) -> tuple[object, object, object]:
            captured["entered"] = True
            return ("READ", "WRITE", lambda: "session-id")

        async def __aexit__(self, *exc: object) -> bool:
            return False

    def fake_streamablehttp_client(
        url: str, headers: dict[str, str] | None = None
    ) -> _FakeStreamCtx:
        captured["url"] = url
        captured["headers"] = headers
        return _FakeStreamCtx()

    class _FakeSession:
        def __init__(self, read: object, write: object) -> None:
            captured["session_streams"] = (read, write)

        async def __aenter__(self) -> _FakeSession:
            return self

        async def __aexit__(self, *exc: object) -> bool:
            return False

        async def initialize(self) -> None:
            captured["initialized"] = True

    monkeypatch.setattr(mc, "streamablehttp_client", fake_streamablehttp_client)
    monkeypatch.setattr(mc, "ClientSession", _FakeSession)

    cfg = ServerConfig(name="r", transport="http", url="https://h/mcp", headers={"A": "1"})
    conn = _ServerConnection(cfg)
    async with AsyncExitStack() as stack:
        await conn._open_session(stack)

    # Only the first two of the 3-tuple reached ClientSession; the third
    # (get_session_id) was unpacked and discarded — no ValueError.
    assert captured["session_streams"] == ("READ", "WRITE")
    assert captured["url"] == "https://h/mcp"
    assert captured["headers"] == {"A": "1"}
    assert captured["initialized"] is True


# ── robustness: connect timeout + wedged-worker teardown ────────────────────


async def test_mcp_connect_timeout_marks_failed_and_does_not_hang(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import code_scalpel.mcp_client as mc

    monkeypatch.setattr(mc, "_SHUTDOWN_GRACE", 0.2)

    # An opener that accepts the connection but hangs forever inside the
    # handshake (a live HTTP url that goes silent / a stdio server that never
    # answers initialize). connect() must time out, the server must be marked
    # failed-with-reason, start() must return, and close() must not hang on the
    # wedged worker.
    started = asyncio.Event()

    async def hanging_opener(stack: AsyncExitStack) -> ClientSession:
        started.set()
        await asyncio.Event().wait()  # never completes — wedged in handshake
        raise AssertionError("unreachable")

    _write_config(tmp_path, {"mcpServers": {"slowboot": {"command": "x"}}})
    mgr = McpManager(
        tmp_path,
        connect_timeout=0.2,
        session_openers={"slowboot": hanging_opener},
    )
    statuses = await asyncio.wait_for(mgr.start(), timeout=5.0)
    assert started.is_set()
    assert len(statuses) == 1
    assert statuses[0].connected is False
    assert statuses[0].reason is not None
    assert "timed out" in statuses[0].reason
    # close() must return promptly even though the worker is wedged in the
    # opener — it cancels the task rather than awaiting it forever.
    await asyncio.wait_for(mgr.close(), timeout=5.0)


async def test_mcp_aclose_cancels_wedged_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Directly exercise _ServerConnection.aclose against a worker that never
    # finishes its handshake: connect() returns False (timeout), the worker task
    # is still pending, and aclose() must cancel it and clear the task.
    import code_scalpel.mcp_client as mc
    from code_scalpel.mcp_client import ServerConfig, _ServerConnection

    monkeypatch.setattr(mc, "_SHUTDOWN_GRACE", 0.2)

    async def hanging_opener(stack: AsyncExitStack) -> ClientSession:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    cfg = ServerConfig(name="w", transport="stdio", command="c")
    conn = _ServerConnection(cfg, session_opener=hanging_opener, connect_timeout=0.2)
    ok = await conn.connect()
    assert ok is False
    assert conn.reason is not None and "timed out" in conn.reason
    task = conn._task
    assert task is not None and not task.done()
    await asyncio.wait_for(conn.aclose(), timeout=5.0)
    assert conn._task is None
    assert task.cancelled() or task.done()


async def test_mcp_close_does_not_hang_inflight_call(tmp_path: Path) -> None:
    # A call is in flight (the tool sleeps) when close() runs. The in-flight
    # future must not hang forever: either it resolves via the call's own
    # timeout or the drain on shutdown. With a tool_timeout shorter than the
    # tool's sleep, the call resolves failed and close() completes promptly.
    async def slow() -> str:
        await asyncio.sleep(5)
        return "done"

    srv = _make_server({"slow": slow})
    mgr = await _manager_with_servers(tmp_path, {"s1": srv}, tool_timeout=0.3)
    await mgr.start()
    call_task = asyncio.create_task(mgr.call_tool("s1.slow", {}))
    await asyncio.sleep(0.05)  # let the call get queued / start
    await asyncio.wait_for(mgr.close(), timeout=5.0)
    outcome = await asyncio.wait_for(call_task, timeout=5.0)
    assert outcome.ok is False


async def test_mcp_queued_call_resolved_on_shutdown(tmp_path: Path) -> None:
    # A _CallRequest enqueued just as the worker shuts down (the reload-during-
    # turn race) must be drained and resolved failed, never left pending. We
    # drive the connection directly: enqueue several calls, then aclose, and
    # assert every future resolved with ok=False.
    from code_scalpel.mcp_client import ServerConfig, _ServerConnection

    srv = _make_server({"echo": _echo_tool})
    cfg = ServerConfig(name="s", transport="stdio", command="c")
    conn = _ServerConnection(cfg, session_opener=_opener_for(srv))
    assert await conn.connect() is True

    # Flood the queue with requests that won't be serviced before shutdown,
    # then close. Each must come back failed rather than hang.
    futs = [conn.call("echo", {"text": str(i)}, 5.0) for i in range(5)]
    await conn.aclose()
    outcomes = await asyncio.wait_for(asyncio.gather(*futs), timeout=5.0)
    assert all(o.ok is False for o in outcomes)


async def test_mcp_call_after_close_returns_failed(tmp_path: Path) -> None:
    # Calling after the server is closed (or while shutting down) must return a
    # failed outcome immediately, never hang on a dead worker.
    srv = _make_server({"echo": _echo_tool})
    mgr = await _manager_with_servers(tmp_path, {"s1": srv})
    await mgr.start()
    await mgr.close()
    outcome = await asyncio.wait_for(mgr.call_tool("s1.echo", {"text": "x"}), timeout=5.0)
    assert outcome.ok is False


async def test_mcp_reload_does_not_hang_inflight_call(tmp_path: Path) -> None:
    # /mcp reload during a turn that is dispatching an MCP tool: reload tears the
    # old connection down; the in-flight call must resolve (failed) rather than
    # hang the turn.
    async def slow() -> str:
        await asyncio.sleep(5)
        return "done"

    srv = _make_server({"slow": slow})
    mgr = await _manager_with_servers(tmp_path, {"s1": srv}, tool_timeout=0.3)
    await mgr.start()
    call_task = asyncio.create_task(mgr.call_tool("s1.slow", {}))
    await asyncio.sleep(0.05)
    try:
        await asyncio.wait_for(mgr.reload(), timeout=5.0)
        outcome = await asyncio.wait_for(call_task, timeout=5.0)
        assert outcome.ok is False
    finally:
        await mgr.close()


# ── robustness: _parse_config never raises on bad field types ───────────────


def test_mcp_parse_config_bad_env_type_is_per_server_error() -> None:
    # env declared as a string (not an object) must produce a per-server config
    # error, not raise out of _parse_config (which would take down all servers
    # on reload).
    raw = {"mcpServers": {"s": {"command": "c", "env": "PATH=/x"}}}
    parsed = {c.name: c for c in _parse_config(raw)}
    assert parsed["s"].transport == ""
    assert parsed["s"].error is not None
    assert "env" in parsed["s"].error


def test_mcp_parse_config_bad_args_type_is_per_server_error() -> None:
    raw = {"mcpServers": {"s": {"command": "c", "args": "--flag"}}}
    parsed = {c.name: c for c in _parse_config(raw)}
    assert parsed["s"].transport == ""
    assert parsed["s"].error is not None
    assert "args" in parsed["s"].error


def test_mcp_parse_config_bad_headers_type_is_per_server_error() -> None:
    raw = {"mcpServers": {"s": {"url": "https://h/mcp", "headers": "Bearer x"}}}
    parsed = {c.name: c for c in _parse_config(raw)}
    assert parsed["s"].transport == ""
    assert parsed["s"].error is not None
    assert "headers" in parsed["s"].error


def test_mcp_parse_config_bad_field_does_not_break_others() -> None:
    # One server with a bad env type alongside a valid one: the valid one still
    # parses, the bad one is a per-server error — no exception.
    raw = {
        "mcpServers": {
            "bad": {"command": "c", "env": ["not", "a", "dict"]},
            "good": {"command": "ok", "args": ["--x"]},
        }
    }
    parsed = {c.name: c for c in _parse_config(raw)}
    assert parsed["bad"].transport == ""
    assert parsed["bad"].error is not None
    assert parsed["good"].transport == "stdio"
    assert parsed["good"].args == ["--x"]


# ── robustness: _load_config falls through a broken file ─────────────────────


def test_mcp_load_config_falls_through_broken_project_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A broken project mcp.json must not mask a valid user (~/.config) config:
    # _load_config falls through to the next location instead of returning {}.
    from code_scalpel import mcp_client as mc

    project = tmp_path / "project"
    (project / ".code-scalpel").mkdir(parents=True)
    (project / ".code-scalpel" / "mcp.json").write_text("{ this is not json ")

    fake_home = tmp_path / "home"
    user_cfg_dir = fake_home / ".config" / "code-scalpel"
    user_cfg_dir.mkdir(parents=True)
    user_payload = {"mcpServers": {"fromuser": {"command": "u"}}}
    (user_cfg_dir / "mcp.json").write_text(json.dumps(user_payload))

    monkeypatch.setattr(mc.Path, "home", staticmethod(lambda: fake_home))

    loaded = McpManager._load_config(project)
    assert loaded == user_payload


def test_mcp_load_config_broken_both_returns_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from code_scalpel import mcp_client as mc

    project = tmp_path / "project"
    (project / ".code-scalpel").mkdir(parents=True)
    (project / ".code-scalpel" / "mcp.json").write_text("{ broken ")

    fake_home = tmp_path / "home"
    user_cfg_dir = fake_home / ".config" / "code-scalpel"
    user_cfg_dir.mkdir(parents=True)
    (user_cfg_dir / "mcp.json").write_text("also { broken")

    monkeypatch.setattr(mc.Path, "home", staticmethod(lambda: fake_home))

    assert McpManager._load_config(project) == {}
