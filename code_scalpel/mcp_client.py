"""MCP (Model Context Protocol) client — official `mcp` SDK, client side only.

The project is an MCP *host/client*: it connects to external MCP servers and
invokes their tools. Two transports are supported — stdio (local subprocess)
and Streamable HTTP (remote). SSE is deliberately not supported (deprecated by
MCP in favour of Streamable HTTP). The project authors no servers.

Cancel-scope task affinity (anyio) is load-bearing here: `stdio_client`,
`streamablehttp_client`, and `ClientSession` each wrap an anyio cancel scope
that MUST be entered and exited in the same task, and the `AsyncExitStack`
owning them must be opened and `aclose()`d in that same task, strict LIFO.
Servers have independent lifetimes (one can fail while others run; `reload`
tears one down without touching the rest), so each server owns its own task
and its own `AsyncExitStack`. A worker task opens the connection, services
call requests over a queue, and closes the stack in-task on shutdown — no
stack is ever entered in one task and closed in another. See
docs/stack-notes.md `### mcp` (python-sdk issues #577/#79/#521).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack, suppress
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.exceptions import McpError
from mcp.types import CallToolResult, TextContent, Tool

# Separator between server name and bare tool name in the namespaced tool id
# the model sees. A dot keeps it readable (`browser.navigate`) and matches the
# `server.tool` convention from the plan.
_NS = "."

# Default per-call timeout if the manager is built without an explicit one
# (e.g. a test that doesn't thread a config through). The real default lives
# in AgentConfig.mcp_tool_timeout and is passed in by callers.
_DEFAULT_TOOL_TIMEOUT = 30.0

# The per-call timeout is enforced by our own wall-clock `asyncio.wait_for`
# (authoritative — it yields a single, consistent "tool call timed out"
# message). The SDK's own `read_timeout_seconds` is kept only as a slower
# backstop: set deliberately ABOVE the wall-clock by this margin so the
# wall-clock always fires first. Equal timers race — and the SDK timer won
# nondeterministically on some interpreters, surfacing its own McpError text
# instead of ours (CI 3.11 vs 3.12 diverged on exactly this).
_SDK_TIMEOUT_BACKSTOP_MARGIN = 5.0

# Default connect/handshake timeout if the manager is built without an explicit
# one. The real default lives in AgentConfig.mcp_connect_timeout. Bounds the
# subprocess spawn / HTTP open + `initialize` + first `tools/list` so a
# live-but-silent endpoint can't wedge startup forever.
_DEFAULT_CONNECT_TIMEOUT = 10.0

# Grace period (seconds) the worker is given to finish closing its own stack
# after a _Shutdown sentinel before we cancel it. Short on purpose: the clean
# path only has to unwind an AsyncExitStack, which takes milliseconds. If a
# connect hangs inside `initialize()` the worker never reaches the shutdown
# loop, so cancellation is the only way out — keeping this small bounds how long
# close()/quit waits on a wedged worker before falling back to cancel.
_SHUTDOWN_GRACE = 2.0


@dataclass(frozen=True)
class ServerConfig:
    """One parsed MCP server entry. Exactly one transport is selected by which
    fields are present: `command` → stdio, `url` → HTTP. An entry carrying
    neither or both is a config error (`error` set, transport left empty)."""

    name: str
    transport: str  # "stdio" | "http" | ""
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] | None = None
    url: str | None = None
    headers: dict[str, str] | None = None
    error: str | None = None  # set when the entry is malformed


@dataclass
class ServerStatus:
    """Per-server connection outcome for `status()` / `/mcp` and the startup
    notice. `connected` is the live state; `reason` carries the failure cause
    when not connected (or the config error)."""

    name: str
    connected: bool
    transport: str
    tool_count: int
    reason: str | None = None
    tools: list[str] = field(default_factory=list)  # namespaced tool names


@dataclass(frozen=True)
class McpToolInfo:
    """A connected MCP tool, namespaced for the model. `qualified_name` is what
    the agent dispatches on; `bare_name` is what the owning server expects in
    `call_tool`."""

    server_name: str
    bare_name: str
    qualified_name: str
    description: str
    input_schema: dict[str, Any]

    def to_openai_schema(self) -> dict[str, Any]:
        params = dict(self.input_schema) if self.input_schema else {}
        if "type" not in params:
            params["type"] = "object"
        return {
            "type": "function",
            "function": {
                "name": self.qualified_name,
                "description": self.description,
                "parameters": params,
            },
        }


@dataclass
class McpCallOutcome:
    """Structured result of a `call_tool`. `ok` is the real success derived
    from the two-tier error model (`isError` / `McpError`), never sniffed from
    the text. `output` is the concatenated textual content (or the failure
    reason)."""

    ok: bool
    output: str


def _parse_config(raw: dict[str, Any]) -> list[ServerConfig]:
    """Parse the `mcpServers` (preferred) / `servers` (legacy) map into a list
    of ServerConfig. `mcpServers` wins when both are present. Transport is
    chosen by field presence; neither/both → a per-server config error rather
    than a crash."""
    entries = raw.get("mcpServers")
    if not isinstance(entries, dict):
        entries = raw.get("servers")
    if not isinstance(entries, dict):
        return []

    out: list[ServerConfig] = []
    for name, cfg in entries.items():
        if not isinstance(cfg, dict):
            out.append(ServerConfig(name=name, transport="", error="entry is not an object"))
            continue
        has_command = bool(cfg.get("command"))
        has_url = bool(cfg.get("url"))
        if has_command and has_url:
            out.append(
                ServerConfig(
                    name=name,
                    transport="",
                    error="entry declares both 'command' and 'url' — pick one transport",
                )
            )
            continue
        if has_command:
            raw_args = cfg.get("args", [])
            if not isinstance(raw_args, list):
                out.append(
                    ServerConfig(name=name, transport="", error="'args' must be a list of strings")
                )
                continue
            raw_env = cfg.get("env")
            if raw_env is not None and not isinstance(raw_env, dict):
                out.append(ServerConfig(name=name, transport="", error="'env' must be an object"))
                continue
            out.append(
                ServerConfig(
                    name=name,
                    transport="stdio",
                    command=str(cfg["command"]),
                    args=[str(a) for a in raw_args],
                    env={str(k): str(v) for k, v in raw_env.items()} if raw_env else None,
                )
            )
            continue
        if has_url:
            raw_headers = cfg.get("headers")
            if raw_headers is not None and not isinstance(raw_headers, dict):
                out.append(
                    ServerConfig(name=name, transport="", error="'headers' must be an object")
                )
                continue
            out.append(
                ServerConfig(
                    name=name,
                    transport="http",
                    url=str(cfg["url"]),
                    headers={str(k): str(v) for k, v in raw_headers.items()}
                    if raw_headers
                    else None,
                )
            )
            continue
        out.append(
            ServerConfig(
                name=name,
                transport="",
                error="entry declares neither 'command' (stdio) nor 'url' (http)",
            )
        )
    return out


def _extract_text(result: CallToolResult) -> str:
    """Read tool output from `CallToolResult.content[].text`. Content is a
    heterogeneous union (TextContent / ImageContent / EmbeddedResource / …);
    only TextContent carries `.text`, so type-narrow before reading. Source:
    docs/stack-notes.md `### mcp` (MCP spec 2025-06-18 result shape)."""
    parts: list[str] = []
    for block in result.content:
        if isinstance(block, TextContent):
            parts.append(block.text)
    return "\n".join(parts)


# A session-opener enters the transport + ClientSession into the given stack
# and returns the initialized session. The real one uses stdio/HTTP transports;
# tests inject an in-memory variant to drive the same worker/call path without a
# subprocess or socket.
SessionOpener = Callable[[AsyncExitStack], Awaitable[ClientSession]]


# Sentinels for the per-server worker request queue.
class _Shutdown:
    pass


@dataclass
class _CallRequest:
    bare_name: str
    arguments: dict[str, Any]
    timeout: float
    future: asyncio.Future[McpCallOutcome]


class _ServerConnection:
    """One MCP server connection, driven entirely from a single worker task so
    the anyio cancel scopes / AsyncExitStack obey task affinity. `connect()`
    launches the worker and waits for the handshake; `call()` hands a request
    to the worker and awaits its reply; `aclose()` signals shutdown and lets
    the worker close its own stack in-task."""

    def __init__(
        self,
        cfg: ServerConfig,
        *,
        session_opener: SessionOpener | None = None,
        connect_timeout: float = _DEFAULT_CONNECT_TIMEOUT,
    ) -> None:
        self._cfg = cfg
        # When set, used instead of the real stdio/HTTP transports — the test
        # seam for an in-memory MCP server. The worker/call/teardown path is
        # otherwise identical, so tests exercise the real logic.
        self._session_opener = session_opener
        self._connect_timeout = connect_timeout
        self._queue: asyncio.Queue[_CallRequest | _Shutdown] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self._ready: asyncio.Future[None] | None = None
        # Set once the worker breaks out of its serve loop (clean _Shutdown or
        # an error after readiness) so call() can fail fast instead of queueing
        # into a worker that will never service the request.
        self._shutting_down = False
        self.tools: list[Tool] = []
        self.connected = False
        self.reason: str | None = None

    async def connect(self) -> bool:
        """Start the worker and wait until it either completes the MCP
        handshake + tool listing or fails. Returns True on success. Never
        raises — a failure (including a connect/handshake timeout) is captured
        in `self.reason`. On timeout the worker may still be wedged inside
        `initialize()`; `aclose()` is responsible for cancelling it so quit
        never blocks."""
        loop = asyncio.get_running_loop()
        self._ready = loop.create_future()
        self._task = asyncio.create_task(self._run(), name=f"mcp:{self._cfg.name}")
        try:
            await asyncio.wait_for(self._ready, timeout=self._connect_timeout)
            self.connected = True
            return True
        except TimeoutError:
            self.reason = f"connect timed out after {self._connect_timeout:g}s"
            self.connected = False
            return False
        except Exception as e:  # noqa: BLE001 — surface any connect failure as a reason
            self.reason = str(e) or e.__class__.__name__
            self.connected = False
            return False

    async def _open_session(self, stack: AsyncExitStack) -> ClientSession:
        """Open the transport + session inside the worker's stack. stdio yields
        a 2-tuple `(read, write)`; Streamable HTTP yields a 3-tuple
        `(read, write, get_session_id)` — the third element is a callable and
        must be unpacked (a 2-tuple unpack raises). Source: docs/stack-notes.md
        `### mcp` (python-sdk v1.28.0 streamable_http.py)."""
        if self._session_opener is not None:
            return await self._session_opener(stack)
        if self._cfg.transport == "stdio":
            params = StdioServerParameters(
                command=self._cfg.command or "",
                args=self._cfg.args,
                env=self._cfg.env,
            )
            read, write = await stack.enter_async_context(stdio_client(params))
        elif self._cfg.transport == "http":
            read, write, _get_session_id = await stack.enter_async_context(
                streamablehttp_client(self._cfg.url or "", headers=self._cfg.headers)
            )
        else:
            raise RuntimeError(self._cfg.error or "no transport selected")
        session: ClientSession = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        return session

    async def _run(self) -> None:
        """Worker body. Opens the connection, signals readiness, then services
        call requests until shutdown — all within the one task that owns the
        AsyncExitStack, so the stack is opened and aclosed in the same task."""
        assert self._ready is not None
        stack = AsyncExitStack()
        try:
            session = await self._open_session(stack)
            listed = await session.list_tools()
            self.tools = list(listed.tools)
        except asyncio.CancelledError:
            # aclose() cancelled us — typically a worker wedged inside
            # `initialize()` after a connect timeout. Best-effort unwind the
            # stack in-task (task affinity) and re-raise so the cancellation
            # completes; do not resolve `_ready` (the connect awaiter has
            # already given up via its wait_for).
            self._shutting_down = True
            self._drain_queue()
            with suppress(Exception):
                await stack.aclose()
            raise
        except Exception as e:  # noqa: BLE001 — any connect/list failure → reason
            with suppress(Exception):
                await stack.aclose()
            if not self._ready.done():
                self._ready.set_exception(e if isinstance(e, Exception) else RuntimeError(str(e)))
            return

        if not self._ready.done():
            self._ready.set_result(None)

        try:
            while True:
                item = await self._queue.get()
                if isinstance(item, _Shutdown):
                    break
                await self._serve_call(session, item)
        finally:
            # Stop accepting new work and fail anything already queued so no
            # caller's `await fut` in call() hangs after shutdown. A _CallRequest
            # can land here via a race — /mcp reload (→ aclose) interleaving with
            # a turn that dispatches an MCP tool — where the request is enqueued
            # just after the _Shutdown sentinel. Draining resolves every such
            # future as a failed outcome instead of leaving it pending forever.
            self._shutting_down = True
            self._drain_queue()
            await stack.aclose()

    def _drain_queue(self) -> None:
        """Resolve every pending _CallRequest left in the queue as a failed
        outcome. Called once at worker shutdown; `_shutting_down` is already set
        so call() won't enqueue more after this point (a request that slips in
        between is failed fast by call() itself)."""
        while True:
            try:
                item = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if isinstance(item, _CallRequest):
                self._resolve(item.future, McpCallOutcome(ok=False, output="error: server closed"))

    async def _serve_call(self, session: ClientSession, req: _CallRequest) -> None:
        """Run one tool call and resolve its future. Maps the two-tier error
        model to `ok`: a raised `McpError` (protocol error) and a returned
        `CallToolResult(isError=True)` (tool-logic error) both → ok=False.
        Output is read from `content[].text`. A wall-clock timeout independent
        of the SDK timer guards a hung transport. Source: docs/stack-notes.md
        `### mcp` (MCP spec 2025-06-18 two-tier error model)."""
        if req.future.done():  # caller already gave up (e.g. outer cancel)
            return
        try:
            result: CallToolResult = await asyncio.wait_for(
                session.call_tool(
                    req.bare_name,
                    req.arguments,
                    # Backstop only — kept above the wall-clock below so our
                    # `asyncio.wait_for` deterministically fires first and the
                    # timeout message stays consistent (see the margin const).
                    read_timeout_seconds=timedelta(
                        seconds=req.timeout + _SDK_TIMEOUT_BACKSTOP_MARGIN
                    ),
                ),
                timeout=req.timeout,
            )
        except TimeoutError:
            self._resolve(req.future, McpCallOutcome(ok=False, output="error: tool call timed out"))
            return
        except McpError as e:
            self._resolve(req.future, McpCallOutcome(ok=False, output=f"error: {e}"))
            return
        except Exception as e:  # noqa: BLE001 — transport/unexpected error → ok=False
            self._resolve(req.future, McpCallOutcome(ok=False, output=f"error: {e}"))
            return

        text = _extract_text(result)
        if result.isError:
            self._resolve(req.future, McpCallOutcome(ok=False, output=text or "error: tool failed"))
        else:
            self._resolve(req.future, McpCallOutcome(ok=True, output=text))

    @staticmethod
    def _resolve(future: asyncio.Future[McpCallOutcome], outcome: McpCallOutcome) -> None:
        if not future.done():
            future.set_result(outcome)

    async def call(
        self, bare_name: str, arguments: dict[str, Any], timeout: float
    ) -> McpCallOutcome:
        if self._shutting_down or not self.connected or self._task is None or self._task.done():
            return McpCallOutcome(ok=False, output="error: server not connected")
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[McpCallOutcome] = loop.create_future()
        self._queue.put_nowait(
            _CallRequest(bare_name=bare_name, arguments=arguments, timeout=timeout, future=fut)
        )
        # Close the enqueue/drain race: if the worker began shutting down (and
        # may have already drained the queue) between the guard above and the
        # put, resolve the future here so this call never hangs. _resolve is a
        # no-op if the worker happened to drain it first.
        if self._shutting_down or (self._task is not None and self._task.done()):
            self._resolve(fut, McpCallOutcome(ok=False, output="error: server closed"))
        return await fut

    async def aclose(self) -> None:
        """Signal the worker to shut down and wait for it to close its stack in
        its own task, then return. Never raises and never hangs.

        Happy path: enqueue `_Shutdown`; the worker breaks its serve loop,
        drains queued calls, and aclose()s its stack — all in-task. We await
        that with a short grace.

        Wedged-worker path: a worker stuck inside `initialize()` (a connect that
        timed out) never reaches the serve loop, so the `_Shutdown` sentinel is
        never read. After the grace we `cancel()` it and await the cancellation
        with `suppress(CancelledError)`. This is what keeps quit / `/mcp reload`
        from blocking forever on a server that accepted the connection then went
        silent."""
        if self._task is None:
            return
        self._shutting_down = True
        if not self._task.done():
            self._queue.put_nowait(_Shutdown())
        try:
            await asyncio.wait_for(asyncio.shield(self._task), timeout=_SHUTDOWN_GRACE)
        except TimeoutError:
            # Worker didn't wind down in time (wedged in initialize / a hung
            # transport that won't unwind). Cancel and wait it out so we never
            # leak a pending task into quit.
            self._task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await self._task
        except Exception:  # noqa: BLE001 — worker already failed; nothing to surface
            pass
        self._task = None
        self.connected = False


class McpManager:
    """Manages all MCP server connections for one agent session.

    Public surface (the agent and TUI depend on this):
      - construct from working dir → loads + parses config.
      - `start()` → connects every server; returns per-server status. Never
        raises on one server's failure.
      - `tool_names` → the set of namespaced tool names the agent dispatches on.
      - `tool_schemas()` → OpenAI-function-format schemas (namespaced names).
      - `call_tool(name, args)` → McpCallOutcome with the real `ok`.
      - `status()` → per-server connection state + reason for `/mcp`.
      - `reload()` → graceful teardown + reconnect from current config.
      - `close()` → graceful teardown of all servers.

    `native_tool_names` lets the manager honour the precedence rule: a native
    scalpel tool always wins, so an MCP tool whose namespaced name collides
    with a native name is dropped with a recorded reason and never enters the
    dispatch set or schema list.
    """

    def __init__(
        self,
        project_root: Path,
        *,
        tool_timeout: float = _DEFAULT_TOOL_TIMEOUT,
        connect_timeout: float = _DEFAULT_CONNECT_TIMEOUT,
        native_tool_names: set[str] | None = None,
        session_openers: dict[str, SessionOpener] | None = None,
    ) -> None:
        self._project_root = project_root
        self._tool_timeout = tool_timeout
        self._connect_timeout = connect_timeout
        self._native_tool_names = native_tool_names or set()
        # Per-server-name session-opener override — the test seam for in-memory
        # servers. Production leaves this empty and the real transports are used.
        self._session_openers = session_openers or {}
        self._configs: list[ServerConfig] = _parse_config(self._load_config(project_root))
        self._connections: dict[str, _ServerConnection] = {}
        # qualified tool name → (connection, bare name)
        self._tools: dict[str, McpToolInfo] = {}
        self._routing: dict[str, tuple[_ServerConnection, str]] = {}
        self._status: dict[str, ServerStatus] = {}
        self._started = False

    # ── config loading ──────────────────────────────────────────────────────

    @staticmethod
    def _load_config(project_root: Path) -> dict[str, Any]:
        """Read the first *usable* config from the project dir then the user
        config dir. A malformed JSON / unreadable file at one location does not
        mask a valid config at the next: parse failures fall through to the next
        location rather than returning empty immediately. Only when no location
        yields a usable dict do we fall back to no-servers."""
        for loc in (
            project_root / ".code-scalpel" / "mcp.json",
            Path.home() / ".config" / "code-scalpel" / "mcp.json",
        ):
            if not loc.exists():
                continue
            try:
                data = json.loads(loc.read_text())
            except (json.JSONDecodeError, OSError):
                continue  # a broken file here must not hide a valid one below
            if isinstance(data, dict):
                return data
            # A JSON file that isn't an object (e.g. a list) is unusable at this
            # location; try the next rather than treating it as authoritative.
        return {}

    # ── lifecycle ───────────────────────────────────────────────────────────

    async def start(self) -> list[ServerStatus]:
        """Connect every configured server. Per-server failures are captured in
        the returned status list; a single bad server never aborts the rest and
        never raises out of `start()`."""
        if self._started:
            return self.status()
        self._started = True
        for cfg in self._configs:
            await self._connect_one(cfg)
        return self.status()

    async def _connect_one(self, cfg: ServerConfig) -> None:
        if cfg.transport == "":
            self._status[cfg.name] = ServerStatus(
                name=cfg.name,
                connected=False,
                transport="",
                tool_count=0,
                reason=cfg.error or "invalid config",
            )
            return
        conn = _ServerConnection(
            cfg,
            session_opener=self._session_openers.get(cfg.name),
            connect_timeout=self._connect_timeout,
        )
        ok = await conn.connect()
        if not ok:
            self._status[cfg.name] = ServerStatus(
                name=cfg.name,
                connected=False,
                transport=cfg.transport,
                tool_count=0,
                reason=conn.reason,
            )
            await conn.aclose()
            return
        self._connections[cfg.name] = conn
        self._register_tools(cfg, conn)

    def _register_tools(self, cfg: ServerConfig, conn: _ServerConnection) -> None:
        """Namespace and register a connected server's tools. Skips malformed
        tools (missing name) and drops any whose namespaced name collides with
        a native tool — native always wins. Records loaded tool names in the
        status entry."""
        loaded: list[str] = []
        for tool in conn.tools:
            bare = getattr(tool, "name", "") or ""
            if not bare:
                continue  # malformed tools/list entry — skip, keep the rest
            qualified = f"{cfg.name}{_NS}{bare}"
            if qualified in self._native_tool_names or bare in self._native_tool_names:
                # Native tool wins on collision — drop the MCP tool entirely so
                # it never shadows a built-in at schema-build or dispatch time.
                continue
            if qualified in self._routing:
                continue  # duplicate within the same server — keep the first
            schema = getattr(tool, "inputSchema", None) or {}
            info = McpToolInfo(
                server_name=cfg.name,
                bare_name=bare,
                qualified_name=qualified,
                description=getattr(tool, "description", "") or "",
                input_schema=schema if isinstance(schema, dict) else {},
            )
            self._tools[qualified] = info
            self._routing[qualified] = (conn, bare)
            loaded.append(qualified)
        self._status[cfg.name] = ServerStatus(
            name=cfg.name,
            connected=True,
            transport=cfg.transport,
            tool_count=len(loaded),
            tools=loaded,
        )

    async def reload(self) -> list[ServerStatus]:
        """Graceful teardown + reconnect from the current config on disk."""
        await self.close()
        self._configs = _parse_config(self._load_config(self._project_root))
        return await self.start()

    async def close(self) -> None:
        """Tear down every server. Each connection closes its own stack in its
        own task (task affinity), so closing them is just awaiting each
        worker's shutdown."""
        for conn in list(self._connections.values()):
            await conn.aclose()
        self._connections.clear()
        self._tools.clear()
        self._routing.clear()
        self._status.clear()
        self._started = False

    # ── query surface ───────────────────────────────────────────────────────

    @property
    def tool_names(self) -> set[str]:
        """Namespaced names of all connected tools — the set the agent
        dispatches on."""
        return set(self._routing.keys())

    def tool_schemas(self) -> list[dict[str, Any]]:
        return [info.to_openai_schema() for info in self._tools.values()]

    # Back-compat alias for the previous manager surface (agent/TUI call sites
    # used `get_tool_schemas`); kept so the schema-list call site stays stable.
    def get_tool_schemas(self) -> list[dict[str, Any]]:
        return self.tool_schemas()

    def status(self) -> list[ServerStatus]:
        """Per-server status in config order — invalid/failed servers included
        so `/mcp` and the startup notice can report them with their reason."""
        out: list[ServerStatus] = []
        for cfg in self._configs:
            st = self._status.get(cfg.name)
            if st is not None:
                out.append(st)
            else:
                out.append(
                    ServerStatus(
                        name=cfg.name,
                        connected=False,
                        transport=cfg.transport,
                        tool_count=0,
                        reason="not started",
                    )
                )
        return out

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> McpCallOutcome:
        """Dispatch a namespaced tool call to its owning server, enforcing the
        per-call timeout and the two-tier error model. Returns a structured
        outcome with the real `ok` — never sniffs the text."""
        route = self._routing.get(name)
        if route is None:
            return McpCallOutcome(ok=False, output=f"error: no MCP tool named '{name}'")
        conn, bare = route
        return await conn.call(bare, arguments, self._tool_timeout)
