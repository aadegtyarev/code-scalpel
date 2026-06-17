# MCP SDK rewrite — plan

Source: PM request (2026-06-17) — productionize the MCP integration shipped in v0.14.0; replace the hand-rolled JSON-RPC client with the official `mcp` SDK. Transport/scope decisions made with PM up front (official SDK; stdio + streamable-HTTP; tools-only).

## Scenarios

1. A user with `.code-scalpel/mcp.json` declaring one or more MCP servers launches the TUI; each declared server connects, its tools are listed, namespaced, and made callable by the agent. The chat shows which servers connected and how many tools loaded.
2. The model calls an MCP tool during a turn; the call is dispatched to the owning server, the tool's real result is returned, and a tool result that genuinely failed (`isError` / JSON-RPC error) is reported to the model as a failed tool call (`ok=False`) — not silently swallowed and not misrouted to a native tool.
3. A user runs `/mcp` and sees each configured server, its connection status (connected / failed-with-reason), and the tools it exposes.
4. A user runs `/mcp reload` and the manager tears down and re-establishes the servers from the current config without restarting the TUI.
5. A config uses the standard `mcpServers` key (copied verbatim from a Claude Desktop / other-client config) and it works unchanged; an old config using the legacy `servers` key also still works.
6. A config declares a remote server by `url` (with optional `headers`); it connects over streamable-HTTP. A config declaring `command`/`args`/`env` connects over stdio. Transport is chosen by which fields are present.

**Failure scenarios (external I/O — subprocess + network):**

7. A declared stdio server's `command` is not on PATH / exits immediately: startup continues, the other servers still load, and `/mcp` and the startup notice report that server as failed with the reason. Native tools and the rest of the session are unaffected.
8. A declared HTTP server's `url` is unreachable / returns a non-MCP response / times out on connect: same outcome as 7 — that server is marked failed with reason, others unaffected.
9. An MCP tool call exceeds the configured per-call timeout: the call returns a failed `ToolResult` (timeout reason) to the model rather than hanging the turn; the session stays responsive.
10. An MCP server returns a malformed `tools/list` (missing name, bad schema): the offending tool is skipped with a logged reason; well-formed tools from the same server still load.
11. Two servers expose a tool with the same bare name, or an MCP tool name collides with a native scalpel tool: collisions are resolved deterministically (namespacing; native always wins) so no tool is silently shadowed.

## Existing behaviors this feature touches

(from `docs/user-journeys.md` and the v0.14.0 MCP-in-TUI integration)

- **TUI startup MCP load** (v0.14.0): MCP servers are started in a worker on mount, attached to the live agent, and torn down on unmount. This flow stays; its internals move to the SDK-based manager. The startup notice must keep working and gain failure reporting.
- **Native tool dispatch** (`agent._execute_native`): all built-in tools (`read_file`, `write_file`, `shell_exec`, `load_skill`, …) must keep working exactly as before. The MCP dispatch must not shadow or intercept any native tool.
- **Tool schema list** (`agent._tool_schemas`): native + skill schemas must be unchanged; MCP schemas are appended, namespaced.
- **No-MCP default**: a project with no `mcp.json` behaves exactly as today — no servers, no notice, zero overhead, no new failure modes.
- **Config loading & cwd**: MCP config resolves under the working directory anchored at startup (`.code-scalpel/mcp.json`) and the system path — consistent with the v0.14.0 cwd-anchoring behavior.

## Contracts

- **Config schema** (`.code-scalpel/mcp.json`, and `~/.config/code-scalpel/mcp.json`):
  - Top-level key `mcpServers` (preferred, Claude-Desktop-compatible) **or** `servers` (legacy, back-compat). If both present, `mcpServers` wins.
  - Per-server entry, **stdio**: `{ "command": str, "args": [str], "env": {str: str}? }`.
  - Per-server entry, **HTTP**: `{ "url": str, "headers": {str: str}? }`.
  - Transport selected by presence of `command` vs `url`. An entry with neither (or both) is a config error reported per server, not a crash.
- **Manager public surface** (names illustrative; coder owns exact API):
  - construct from working dir → loads config.
  - `start()` → connects all servers; returns per-server outcome (connected + tool count, or failed + reason). Never raises on a single server's failure.
  - `tool_names` → the set of namespaced MCP tool names the agent dispatches on.
  - `tool_schemas()` → OpenAI-function-format schemas for connected tools (namespaced names).
  - `call_tool(name, args)` → structured result carrying real success (`ok` derived from `isError` / JSON-RPC error) and the textual output; enforces the per-call timeout.
  - `status()` → per-server connection state + reason, for `/mcp`.
  - `reload()` → graceful teardown + reconnect.
  - `close()` → graceful teardown of all servers.
- **Tool namespacing**: MCP tools are exposed to the model under a server-qualified name (e.g. `server.tool`). Native scalpel tool names always take precedence; an MCP tool whose namespaced name still collides with a native name is dropped with a logged reason.
- **Config key** (new, in agent config): per-call MCP tool timeout (seconds), with a sane default.
- **`/mcp` command**: `/mcp` (status + tools), `/mcp reload` (reconnect).
- **Dependency change**: move `mcp` from `[dev]` to `[project.dependencies]`, **capped `mcp>=1.0,<2`** (2.x broke the client API — see Stack expectations). Remove `mcp` from `[dev]` once it is a runtime dep.

## Key design decisions

- **Official SDK over hand-rolled** (PM-confirmed): replace `code_scalpel/mcp_client.py`'s JSON-RPC with `mcp` SDK. Correct handshake, interleaved notifications, typed results/errors, multiple transports.
- **Transports: stdio + streamable-HTTP only** (PM-confirmed). SSE excluded (deprecated).
- **Scope: tools only** (PM-confirmed). Resources/prompts deferred.
- **`call_tool` handles the two-tier error model**: `isError=True` and a raised `McpError` both → `ok=False`; never surfaces a failed MCP call as success, never sniffs result strings.
- **Manager teardown respects cancel-scope task affinity**: each independent-lifetime server owns its task+stack so `reload`/`close` can tear one down without violating LIFO. Coder owns the exact structure.
- **Integration-risk spike — PyInstaller bundling of `mcp`: DONE, PASSED** (2026-06-17, mcp 1.27.2 / PyInstaller 6.20.0). Froze a script importing the mcp client surface with `--collect-all mcp --collect-all pydantic --collect-all pydantic_core --collect-data jsonschema_specifications`; the `--onefile` binary ran in a clean `env -i` and printed OK. Recipe promoted to `execution-verified` in `docs/stack-notes.md`. **`release.yml` must add exactly these four collect flags** to the PyInstaller invocation.

## Stack expectations touched

(from `docs/stack-notes.md` `### mcp` — authored by pm-stack-researcher for this feature; 21 sourced rules. Load-bearing items below; full citations in the entry.)

- **mcp SDK — version cap is mandatory**: the current `mcp>=1.0` pin is **unbounded**, and the SDK 2.x line has **already broken** the client API (`streamablehttp_client` renamed, `read_timeout_seconds` retyped, `ClientSession` streams made optional). Every idiom this plan relies on is the **1.x** contract. The dep **must be capped `mcp>=1.0,<2`** when promoted from `[dev]` to runtime, or it silently breaks. Source: `docs/stack-notes.md` `### mcp` (PyPI release metadata + python-sdk `v1.28.0`).
- **mcp SDK — client lifecycle**: sessions must be driven through the SDK's async context managers (`stdio_client(StdioServerParameters(...))` / `streamablehttp_client(url, headers=…)` → `ClientSession(...)` → `await session.initialize()`), then `session.list_tools()` / `session.call_tool(...)`. No hand-rolled JSON-RPC. Source: `docs/stack-notes.md` `### mcp` (official client quickstart).
- **mcp SDK — cancel-scope task affinity**: an `AsyncExitStack` owning MCP context managers must be opened **and** `aclose()`d in the **same task**, strict LIFO. Servers with independent lifetimes need a task+stack each (anyio cancel-scope constraint). This shapes the manager's teardown/reload design. Source: `docs/stack-notes.md` `### mcp` (python-sdk issues #577/#79/#521).
- **mcp SDK — streamable-HTTP 3-tuple**: `streamablehttp_client(url, headers=…)` yields `(read, write, get_session_id)` — the third element is a callable; unpacking as a 2-tuple raises. Source: `docs/stack-notes.md` `### mcp`.
- **mcp SDK — two-tier error model**: tool-logic failures return `CallToolResult(isError=True)` (no exception); protocol failures raise `McpError`. `call_tool` must handle **both** → map to `ok=False`. Output is read from `CallToolResult.content[].text`. Source: `docs/stack-notes.md` `### mcp` (spec 2025-06-18).
- **mcp SDK — streamable-HTTP entrypoint name**: `streamablehttp_client` is stable across the whole `>=1.0,<2` line (the `streamable_http_client` rename is 2.x); use the `streamablehttp_client` form now. Source: `docs/stack-notes.md` `### mcp`.
- **asyncio**: never block the event loop; subprocess spawn / network connect run in async paths off the first paint. Source: `docs/stack-notes.md` (asyncio entry).
- **PyInstaller packaging**: `mcp` becomes a runtime dependency and must be bundled into the `--onefile` binary. The doc-cited recipe is `--collect-all mcp --collect-all pydantic --collect-all pydantic_core --collect-data jsonschema_specifications` (the `pydantic_core._pydantic_core` and jsonschema-data failure modes are the attested hazards). **This is `doc-cited (unverified)` for this binary** — see the Integration-risk spike below. Validated by the frozen-binary `import mcp` smoke. Source: `docs/stack-notes.md` `### mcp` + packaging entry (PyInstaller docs, issues #570).

## Interaction scenarios

(MCP touches subprocess I/O, network I/O, the shared agent tool registry, the asyncio loop, and the running turn — not isolated.)

- When the MCP startup worker is still connecting servers and the user submits the **first turn**: the turn must run with whatever tools are ready; the agent must not error on a half-initialized manager, and tools that connect mid-flight are available from the next turn.
- When an MCP **tool call is in flight and the server hangs**: the per-call timeout fires, the turn continues, and the session does not deadlock (no blocking readline on the event loop).
- When `/mcp reload` runs **while a turn is using an MCP tool**: reload must not corrupt an in-flight call — either it waits for/cancels cleanly, or it is rejected while a turn is active (coder picks; behavior must be defined and tested).
- When an MCP server name/tool collides with a **native tool** registered in the same session: native dispatch wins; the MCP tool is not reachable under the native name (no shadowing of `shell_exec`, `write_file`, etc.).
- When the agent receives a tool call whose name is **not** an MCP tool: it must fall through to native dispatch with no MCP round-trip and no `"error:"` string-sniffing.

## Test plan

- Existing tests that must pass: all existing tests (notably the agent dispatch / tool-schema tests and the TUI app tests).
- New tests:
  - `test_mcp_config_prefers_mcpServers_over_servers`: given a config with both keys, when loaded, then `mcpServers` entries win and `servers` is ignored.
  - `test_mcp_config_legacy_servers_key`: given a legacy `servers`-only config, when loaded, then servers parse correctly.
  - `test_mcp_transport_selected_by_fields`: given entries with `command` vs `url`, when loaded, then stdio vs HTTP transport is chosen; an entry with neither/both is reported as a per-server config error (not a crash).
  - `test_mcp_namespacing_between_servers`: given two servers exposing the same bare tool name, when tools are registered, then both are reachable under distinct namespaced names.
  - `test_mcp_native_tool_wins_on_collision`: given an MCP tool whose name collides with a native tool, when schemas/dispatch are built, then the native tool is dispatched and the MCP tool is dropped with a logged reason.
  - `test_mcp_call_tool_maps_isError_to_ok_false`: given a fake in-memory server returning `isError`, when `call_tool` runs, then the result is `ok=False` with the server's text — not treated as success.
  - `test_mcp_call_tool_success`: given a fake server returning normal `TextContent`, when `call_tool` runs, then `ok=True` and the text is returned.
  - `test_mcp_call_tool_timeout`: given a fake server that delays past the per-call timeout, when `call_tool` runs, then it returns a failed result (timeout reason) and does not hang.
  - `test_mcp_start_reports_per_server_failure`: given one good and one broken server (bad command / unreachable url), when `start()` runs, then the good one connects and the broken one is reported failed-with-reason; `start()` does not raise.
  - `test_mcp_malformed_tools_list_skips_bad_tool`: given a server returning a tool missing its name/schema, when listing, then the bad tool is skipped and good tools still load.
  - `test_agent_dispatches_mcp_tool_by_name`: given the agent has an MCP tool registered, when the model calls that name, then it routes to `mcp.call_tool` (verified via the set-membership path), and a native tool name still routes to native dispatch with no MCP call.
  - `test_agent_native_tool_not_intercepted_by_mcp`: regression for the v0.14 `"error:"`-sniffing bug — a native tool whose output legitimately starts with `"error:"` is not re-routed.
- Interaction scenario tests:
  - `test_first_turn_during_mcp_startup`: sets up a manager mid-initialization, runs a turn, verifies no error and that ready tools are usable.
  - `test_reload_during_active_turn`: sets up an in-flight MCP call, triggers reload, verifies the defined behavior (clean wait/cancel or rejection) with no corruption.
  - `test_collision_native_vs_mcp_dispatch`: registers a colliding pair, verifies native dispatch wins at call time (not just in schema building).
- Stack-spec tests (one per stack expectation, referencing the stack-notes source URL in a comment):
  - `test_mcp_streamable_http_handles_three_tuple`: verifies the client consumes the `(read, write, get_session_id)` 3-tuple per the SDK contract (not a 2-tuple assumption).
  - `test_mcp_result_content_extraction`: verifies output is read from `CallToolResult.content[].text` per the SDK result shape, against a fixture shaped like the real `CallToolResult` — not the coder's own dict shape.
- Build/packaging check (not a unit test): the release binary smoke-imports `mcp` (and runs `code-scalpel --version`); CI's PR smoke build exercises the bundle.

## Test-wiring parity

MCP correctness depends on registration/wiring (the manager attached to the agent so its tools enter the schema list and dispatch set). At least one test must drive the **same attach path the TUI uses** — manager built, started, attached to the agent — and assert the observable post-condition (`mcp tool name ∈ agent dispatch set` and present in `agent._tool_schemas()`), not a hand-rolled equivalent.

## Docs to update

- `docs/threat-model.md`: add threat rows + a trust-boundary row for MCP. New surfaces: (a) **MCP server subprocesses run outside the `bwrap` sandbox / `policy.py` gate and outside the cwd pin** — they are launched only from user-authored config, never model-derived (record as the bounding rule); (b) **remote MCP endpoint (HTTP)** — tool args sent to a user-configured external endpoint (exfiltration vector; endpoint trust is the user's choice, consistent with the existing network-out-of-scope stance); (c) **MCP tool output re-enters model context** — a new prompt-injection vector analogous to T08 (`/learn`/web fetch), unsanitized today. Bump **Last reviewed**. (Updated by `pm-architect` post-coding.)
- `docs/architecture.md`: add a new `SCn` to `## Security surface` capturing the bounding rule — MCP servers are launched only from user-authored config (not model-derived); tool calls are bounded by a per-call timeout; tool output is untrusted content. Add a decision record for adopting the official SDK + the two supported transports. (Updated by `pm-architect`.)
- `docs/user-journeys.md`: add the MCP journey — configure `mcp.json`, see servers connect on startup, the model uses MCP tools, `/mcp` / `/mcp reload`. (Updated by `pm-architect`.)
- `docs/stack-notes.md`: the `mcp` SDK entry (authored by `pm-stack-researcher` for this feature) — reconcile the "Stack expectations touched" quotes from it.
- `README.md`: MCP setup is part of quick-start/config (README-currency: touches quick-start/config surface) — point to `mcp.example.json` and the standard `mcpServers` schema. (Updated by `pm-architect` on the docs handoff.)
- `mcp.example.json`: update to the `mcpServers` key and show both a stdio and an HTTP server example.
- `.ai-dev` pipeline / quality config: add the new validator from the stack-researcher's "New validators" list (binary `mcp` smoke-import), so the bundling regression is caught in CI.

## Out of scope

- **MCP resources and prompts** — only `tools` this iteration; resources/prompts are a separate plan (different surface: where server-provided data/templates attach in the TUI/context is its own UX decision).
- **SSE transport** — deliberately excluded; deprecated by MCP in favor of streamable-HTTP. A server that only speaks SSE is unsupported (its own plan if ever needed).
- **OAuth / interactive auth flows for remote servers** — only static `headers` (e.g. a bearer token) this iteration; full auth handshakes are separate.
- **Authoring MCP servers** — code-scalpel is a client only.
- **Sandboxing MCP server subprocesses** — bounded by user-authored-config trust + per-call timeout this iteration; running MCP servers inside `bwrap` is a separate hardening plan (noted in the threat model as residual).
- **Auto-reconnect / health-polling of dropped servers** — `/mcp reload` is manual this iteration.
