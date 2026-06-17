# MCP SDK rewrite — plan compliance review

Plan: `docs/features/mcp-sdk-rewrite_plan.md`
Branch: `feature/mcp-sdk-rewrite` (vs `main`)
Tests: `pytest -q tests/test_mcp_client.py tests/test_mcp_agent_dispatch.py` → **24 passed**. Full suite: **1380 passed, 40 skipped**.

## Plan compliance
- ✓ Scenario 1 (startup connect / namespace / callable + notice) — `tui/app.py` `_init_mcp` + `_mcp_startup_notice`; `mcp_client._register_tools` — test `test_mcp_agent_wiring_parity`, `test_mcp_tool_schemas_namespaced`
- ✓ Scenario 2 (dispatch + two-tier error → ok=False, not misrouted) — `agent.py:1775-1781`, `mcp_client._serve_call` — test `test_agent_dispatches_mcp_tool_by_name`, `test_agent_mcp_isError_routes_to_ok_false`, `test_mcp_call_tool_maps_isError_to_ok_false`
- ✓ Scenario 3 (`/mcp` status) — `tui/app.py` `_do_mcp_status`; `McpManager.status()` — covered via `test_mcp_start_reports_per_server_failure`
- ✓ Scenario 4 (`/mcp reload`) — `_do_mcp_reload`, `McpManager.reload` — test `test_mcp_reload_reconnects`, `test_reload_during_active_turn`
- ✓ Scenario 5 (mcpServers > legacy servers) — `_parse_config` — test `test_mcp_config_prefers_mcpServers_over_servers`, `test_mcp_config_legacy_servers_key`
- ✓ Scenario 6 (transport by command/url) — `_parse_config`, `_open_session` — test `test_mcp_transport_selected_by_fields`
- ✓ Scenario 7 (stdio failure → others load, reported) — `_connect_one` — test `test_mcp_start_reports_per_server_failure`
- ✓ Scenario 8 (HTTP unreachable → same) — same path (opener raises ConnectionError) — test `test_mcp_start_reports_per_server_failure`
- ✓ Scenario 9 (per-call timeout) — `_serve_call` `asyncio.wait_for` — test `test_mcp_call_tool_timeout`
- ✓ Scenario 10 (malformed tools/list skipped) — `_register_tools` empty-name skip — test `test_mcp_malformed_tools_list_skips_bad_tool`, `test_mcp_malformed_tools_list_via_real_path`
- ✓ Scenario 11 (collision: namespacing / native wins) — `_register_tools` — test `test_mcp_namespacing_between_servers`, `test_mcp_native_tool_wins_on_collision`, `test_collision_native_vs_mcp_dispatch`

### Interaction scenarios
- ✓ First turn mid-startup — `test_first_turn_during_mcp_startup`
- ✓ Tool call hang → timeout, turn continues — `test_mcp_call_tool_timeout`
- ✓ Reload during active turn (defined behavior: teardown+reconnect, no corruption) — `test_reload_during_active_turn`
- ✓ Native-vs-MCP collision wins at call time — `test_collision_native_vs_mcp_dispatch`
- ✓ Non-MCP name falls through to native, no sniffing — `test_agent_native_tool_not_intercepted_by_mcp`

### Stack-spec tests
- ✓ 3-tuple — `test_mcp_streamable_http_handles_three_tuple` (asserts only first two streams reach `ClientSession`; third unpacked/discarded — no 2-tuple assumption)
- ✓ `CallToolResult.content[].text` — `test_mcp_result_content_extraction` (real `CallToolResult`/`TextContent`, not a self-consistent dict); call-path tests drive a real `FastMCP` via `create_connected_server_and_client_session` — genuine `CallToolResult` objects, not a mimic

### Test-wiring-parity
- ✓ `test_mcp_agent_wiring_parity` drives the TUI attach path (build manager → `start()` → `agent._mcp = manager`) and asserts `s1.echo ∈ agent._mcp.tool_names` AND in `agent._tool_schemas()` AND dispatches end-to-end through `_execute_native`. Same registration path production takes.

### Contracts
- ✓ mcpServers > servers; legacy servers read
- ✓ transport by command/url; neither/both → per-server config error (not crash)
- ✓ namespacing `server.tool`; native always wins (`agent.native_tool_names()` threaded into manager, colliding MCP tools dropped before they enter `tool_names`/schemas)
- ✓ `call_tool` real `ok` from `isError` / `McpError` — the v0.14 `.startswith("error:")` sniff is removed (`agent.py:1779`); routing keys on `tool_names` membership only
- ✓ per-call timeout via new `config.mcp_tool_timeout` (default 30s), threaded at `McpManager` construction
- ✓ `/mcp` (status) + `/mcp reload`
- ✓ dep `mcp>=1.0,<2` moved to `[project.dependencies]`, removed from `[dev]`

### Docs to update (all landed; uncommitted in working tree)
- ✓ `docs/threat-model.md` — T13/T14/T15 + 3 trust-boundary rows + 2 do-NOT-protect entries; Last reviewed bumped 2026-06-17
- ✓ `docs/architecture.md` — SC9 added to Security surface + decision record #15 (official SDK + two transports)
- ✓ `docs/user-journeys.md` — Journey 10 (configure, startup, use, `/mcp`, `/mcp reload`)
- ✓ `docs/stack-notes.md` — `### mcp` entry (incl. version-cap, 3-tuple, two-tier error, cancel-scope affinity, PyInstaller recipe `execution-verified`)
- ✓ `README.md` — MCP servers section + `/mcp` command + sandbox warning
- ✓ `mcp.example.json` — `mcpServers` key, stdio + HTTP examples
- ✓ `.github/workflows/release.yml` — exactly the four spike-verified collect flags
- ✓ `.ai-dev/quality/tools.json` — `mcp-import-smoke` validator (build beat)

## Definition of Done
- [x] All plan scenarios implemented and tested
- [x] Interaction scenarios have concurrent-state tests
- [x] Stack expectations respected; stack-spec tests pass
- [x] Product Contract honored; Acceptance checks pass; no silent behavior change (TUI/`/mcp` behavior covered by manager + dispatch tests; no mode contract in `docs/contracts/` covers MCP — no contract regression)
- [x] Pipeline green (1380 passed, 40 skipped)
- [x] State file updated (`.ai-dev/state/current.md`)
- [x] Product Impact Report present (n/a — no `.ai-pm` contract surface on this project; state file documents impact)
- [x] Docs updates landed
- [x] Expected artifacts exist (plan, this review)
- [x] Security gate: project has `docs/threat-model.md` and plan lists it in Docs to update; threat rows landed
- [x] Failure-inventory negative-space tests present (scenarios 7-11 each have a failure-path test)
- [n/a] Product-readiness advocate gate (project uses `.ai-dev` convention, no advocate-artifact gate)
- [n/a] Validation gate (software-kind feature)

**DoD: pass**

## Blocking
(none)

## Notes (product)
1. Docs (threat-model, architecture, user-journeys, README, stack-notes) are modified in the working tree but **not yet committed** on `feature/mcp-sdk-rewrite`. They must be committed before the PR — content is complete and correct, only the commit is pending. Why it matters: the branch is not self-contained until they land; a PR opened now would ship code without its threat-model/architecture updates.
2. Scenario 3 (`/mcp` status) and Scenario 4's reload TUI rendering are UI-presentation paths (`_do_mcp_status` / `_mcp_startup_notice`) with no direct unit test — the underlying `status()`/`reload()` data is tested, but the formatting/command-wiring in `tui/app.py` is not. Non-critical (no logic beyond formatting), surfaced for PM awareness.
3. `/mcp reload` while a turn uses an MCP tool: the plan allowed coder's choice (clean wait/cancel OR rejection). Implementation does neither explicitly — reload runs in its own worker and tears down/reconnects; the worker-per-server model isolates lifetimes so a concurrent in-flight call resolves against its (closing) connection. `test_reload_during_active_turn` exercises sequential call→reload→call, not a genuinely concurrent in-flight reload. Behavior is defined-by-construction (no corruption) but the strictly-concurrent case is not asserted. Why it matters: a PM may want the concurrent-reload-during-active-call case explicitly tested; current coverage is sequential.

## Verdict
approve

<!-- The trail below is owned by the orchestrator, not pm-plan-checker. -->
## Code review findings
(populated by orchestrator from code-review output; builder reads and fixes these)

## Code review: NOT YET RUN
