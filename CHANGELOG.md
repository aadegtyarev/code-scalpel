# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.16.1] — 2026-06-17

### Fixed
- MCP per-call timeout produced an inconsistent message and a CI failure on
  Python 3.11: our wall-clock `asyncio.wait_for` and the SDK's
  `read_timeout_seconds` were both set to the same value and raced, so the
  timeout surfaced either our "tool call timed out" text or the SDK's
  `McpError` text depending on the interpreter. The SDK timer is now a
  backstop set above the wall-clock, so the wall-clock always wins and the
  message is deterministic.

### Docs
- Install claims aligned with reality across `README`, `docs/product.md`, and
  `docs/architecture.md`: GitHub Releases (`.deb` + standalone binary) is the
  canonical channel; PyPI is marked planned/not-yet-published.

## [0.16.0] — 2026-06-17

### Security
- External tool/web output is now framed as untrusted before it reaches the
  model. MCP tool results and web-search results are wrapped in a delimited
  `⟦UNTRUSTED⟧` block tagged with their source, and the system prompt carries a
  rule that content inside such a block is data — never instructions. Framing
  only (no active pattern-stripping); the wrapper neutralizes any inner
  delimiter so a payload can't break out, and the framing survives context
  compression. Resolves the threat-model T08/T15 open questions (SC10);
  residual: the `/learn --url` → recipe path is deferred to a source-aware
  recipe-injection follow-up.

### Changed
- `code-scalpel --selfcheck` (hidden): imports and exercises the
  bundle-sensitive runtime (mcp client, a pydantic_core model, the
  jsonschema_specifications packaged data, and the TUI/manager chain), exiting
  non-zero on any gap. The release build runs it after the binary build so a
  broken PyInstaller `--collect-*` recipe fails CI instead of shipping — the
  gap `--version` could not catch.

## [0.15.0] — 2026-06-17

### Changed
- MCP rewritten on the official `mcp` SDK (was a hand-rolled JSON-RPC client).
  Correct handshake, interleaved notifications, typed results, and two
  transports: stdio (local subprocess) and streamable-HTTP (remote). `mcp` is
  now a runtime dependency, capped `>=1.0,<2`.
- Config accepts the standard `mcpServers` key (Claude-Desktop-compatible);
  the legacy `servers` key still works. Transport is chosen by `command` vs
  `url`. `mcp.example.json` updated with stdio + HTTP examples.
- Tool dispatch is clean: MCP tools are routed by namespaced name
  (`server.tool`) before native dispatch; native tools always win on a name
  collision. The previous `"error:"`-string sniffing is gone.

### Added
- `/mcp` (per-server status + tools) and `/mcp reload` (reconnect without
  restarting the TUI). Startup notice reports loaded tool count and any
  failed server with its reason.
- Per-call tool timeout (`agent.mcp_tool_timeout`) and connect/handshake
  timeout (`agent.mcp_connect_timeout`) so a slow or wedged server never
  hangs a turn, startup, or quit.

### Security
- New trust-boundary coverage for MCP in the threat model (T13–T15) and a new
  rule SC9 in the architecture: MCP servers are launched only from
  user-authored config (never model-derived), tool calls are bounded by a
  per-call timeout, and MCP tool output is treated as untrusted content.

### Fixed
- Robust config parsing: a malformed server entry (bad `env`/`headers`/`args`
  type, both/neither transport fields) becomes a per-server error instead of
  disabling all MCP. A broken project `mcp.json` no longer masks a valid
  user-level config.

## [0.14.0] — 2026-06-17

### Added
- MCP (Model Context Protocol) support in the TUI. Servers declared in
  `.code-scalpel/mcp.json` are launched on startup, their tools are attached to
  the live agent, and a load notice is shown in the chat; subprocesses are torn
  down cleanly on exit. This surfaces the MCP client (browser automation and
  more) that previously existed in the backend but was unreachable from the TUI.

### Changed
- Launching from any directory now anchors the whole process there:
  `code-scalpel` (and `code-scalpel --path <dir>`) `chdir`s into the target and
  loads that project's `config.yaml` / `.env`, so config, edits, and shell all
  resolve against the working tree the user expects.
- Install documentation reworked around the canonical `.deb` package and
  standalone binary from GitHub Releases; PyPI is marked as not-yet-published.

### Fixed
- `mcp.example.json` updated to stdio transport (the SSE / `--port` path was
  removed earlier and the example was stale).
- Two pre-existing strict-mypy `no-any-return` errors in `mcp_client.py`.

## [0.13.0] — 2026-06-16

### Added
- Flat-layout run-smoke. The acceptance gate can now find and run the CLI of a
  flat-layout Python project — one where the package sits at the repo root
  rather than under `src/`. It recognises three shapes, in a fixed order of
  preference: a root package with a `__main__.py` (run as `python -m pkg`), a
  single root entry script such as `cli.py` / `main.py` / `__main__.py` (run
  directly), and a single declared console command from `[project.scripts]`. A
  declared console command always wins over a discovered script; if the project
  is ambiguous or has no runnable entry, the gate raises rather than guessing.
  This closes the first of the two reach gaps that left the acceptance gate and
  the self-fix loop inert on the canonical flat-layout scenario.
- New config `run_smoke_script_candidates` lets you set which root script names
  count as entry points; the values are validated against path traversal.
- AI-Dev protocol setup: configured quality toolkit (ruff, mypy, pytest,
  bandit, detect-secrets) with CI wired through the quality runner
  (`node .ai-dev/quality/run.mjs`), ensuring every tool addition automatically
  enters CI.

### Changed
- The acceptance gate now verifies the runnable CLI at the **last task that
  actually builds it**, not merely the last task in the plan. So a CLI finished
  before the final task — for example when the plan ends with a tests-only or
  docs-only task — is still run-smoked, and a failing run-smoke still engages
  the self-fix loop at trust `optimist` / `yolo`. This closes the second reach
  gap. No new task status is introduced, and both existing safety invariants
  hold: an early task is never demoted, and a library (no-CLI) project is never
  failed by this gate.
- Doc bootstrap: migrated system canon from old protocol format. `docs/architecture.md`
  compressed 984→121 lines into current protocol template. Contracts extracted
  from legacy `.ai-pm/contracts/` into `docs/contracts/` (8 files). Threat model
  refreshed. Old-protocol artifacts (`.ai-pm/`, `CLAUDE.md`) deleted — truth
  moved to its single home.
- Project `kind` changed from `code` to `mixed` — both code and documentation
  are first-class products.

## [0.12.5.dev5] — 2026-06-07
Prerelease — content subsumed by 0.13.0.

## [0.12.5.dev4] — 2026-06-07
### Added
- Bounded, trust-gated acceptance self-fix loop. When a runnable CLI
  deliverable's acceptance run-smoke fails on the last applicable task, the
  agent no longer demotes `done → failed` straight away: at trust `optimist`
  or `yolo` it feeds the failing run-smoke output back to the model, rebuilds,
  and re-runs the smoke — up to a bounded budget — before finally failing. At
  `skeptic` it fails immediately and waits for the human, as before.
- The failing run-smoke output is now carried inline into the self-fix attempt,
  so the model sees exactly what broke instead of a bare verdict.
- New config: `acceptance_self_fix` (bool, default **on**) gates the loop, and
  `acceptance_self_fix_max_attempts` (int, default **3**) caps the retries.
### Changed
- Self-fix is **bounded twice over**: by the attempt budget and by an
  identical-run-smoke-output anti-loop early-stop — if a rebuild produces the
  same failing output, the loop stops early rather than burning the budget.
- Self-fix fires only at the single last-applicable-task position; early CLI
  tasks and library / no-spec tasks are never self-fixed, so the blast radius
  of the retry behaviour stays exactly where acceptance enforcement already is.

## [0.12.5.dev3] — 2026-06-06
### Added
- Acceptance specs in tasks — the acceptance gate now has teeth. A task can
  carry a typed `AcceptanceSpec(command, expected, applicable, source)`, and
  the run loop's verification #4 now **enforces** it: when an *applicable* spec
  exists and the deliverable fails to satisfy it, the task is demoted
  `done → failed`. Previously the run-smoke verdict was observational only.
- Args-only acceptance derivation: a narrow pre-loop pass asks the model only
  for `{applicable, args, expected}` and the adapter builds the argv from it —
  no free-form shell is ever derived or executed (security decision). The
  derived spec is written back into the plan. A human-declared prose acceptance
  criterion is treated as a **hint** to this derivation, not executed directly.
- `auto_derive_acceptance` config flag (default **on**) to gate the derivation
  pass.
### Changed
- Enforcement is **applicable-gated**: only deliverables with an applicable
  acceptance spec can be failed by the gate. The `applicable` flag is the
  CLI-vs-library discriminator — the default floor never sets it, so libraries
  and projects without a spec are never wrongly failed (no regression to the
  prior observational behaviour).
- The run loop is now **language-agnostic**: it carries zero language-specific
  strings, so a future adapter (e.g. Node) plugs in without any run-loop edit.

## [0.12.5.dev2] — 2026-06-06
### Added
- Run-smoke plumbing and observability in `run_plan`: after a plan finishes,
  the run loop resolves an acceptance adapter from the skill registry and runs
  the deliverable's run-smoke (`python -m <pkg> --help`), then records and
  surfaces the verdict — whether the deliverable actually ran. This is
  **observational only**: the verdict is reported but never demotes a task to
  `failed`, so there is **no change to which tasks pass or fail** in this
  release. Enforcement (acting on the verdict) is deferred to a later feature,
  because acting on it first requires a reliable CLI-vs-library signal to know
  what "ran" means for a given deliverable.
- Acceptance-adapter mechanism on the skill layer: `Skill.provides_acceptance`,
  `Skill.bind(root)`, and `SkillRegistry.acceptance_adapter` let the run loop
  discover and bind the adapter that knows how to run-smoke a deliverable.
- `AgentState` run-smoke fields to carry the recorded verdict through the run.
### Changed
- Strangled `run_plan` out of the monolithic `agent.py` into focused modules —
  `plan_runner.py`, `plan_loading.py`, `plan_post_checks.py`, and
  `plan_verify.py`. Behavior-preserving refactor, no functional change.

## [0.12.5.dev1] — 2026-06-06
### Added
- ProjectAdapter contract: extends the `Skill` ABC with four non-abstract
  methods (`build_install`, `run_smoke`, `scaffold`, `acceptance_spec`) plus a
  `ScaffoldSpec` value type, and ships the first implementation,
  `PythonCliAdapter`. Pure-additive and inert — the contract is defined and
  registered but not yet wired into the run loop (that is the next feature), so
  there is no behaviour change in this release.
- Registry `hidden` trait: an adapter registered as hidden is discoverable via
  `get_skill` but is not advertised in the model catalog, `active_skills`, or
  `/skills`. This keeps the new adapter available to internal callers while
  remaining invisible to the model until the run-loop consumer lands.
