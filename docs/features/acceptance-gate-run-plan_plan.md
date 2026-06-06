# acceptance-gate-run-plan — plan

Decision authority: autonomous   # per-feature override — PM set "на автомате" for this batch; project default is interactive (no .ai-pm/decision-authority.md)

Source: backend redesign migration step 2, `.ai-pm/arch/backend-redesign_arch.md` ("feat/acceptance-gate-run-plan — FIRST that moves the needle"); PM-greenlit as the next feature. Integration design: `.ai-pm/arch/acceptance-gate-run-plan_arch.md`.

The run-loop **consumer** of the merged ProjectAdapter contract (feature 1, PR #168). It adds a 4th mandatory machine check to `run_plan`'s Definition-of-Done — **the agent actually runs the deliverable the way a user would** (`python -m <pkg>`) — so a task can no longer be `done` on proxies (package import + unit tests on the easy module). Proven root cause (`.ai-pm/arch/backend-redesign_arch.md`): of 52 recent `user_gave_up` runs only 1 (2%) ever invoked the CLI with a real subcommand; the dominant failure is a plausible project whose `python -m <pkg>` does not execute at all (the missing-`__main__.py` coin-flip). The default-floor `python -m <pkg> --help` exit-0 check catches exactly that failure.

**Feature's own acceptance criterion:** the v0.14 outcome gate — `notes_cli` **3/3 consistent `task_solved`** (the "outcome-driven release gate" decision in `docs/architecture.md` finally getting teeth). Plus the Product Contract `## Must not break`: a `done` task means run-smoke passed.

## Scenarios

1. When `run_plan` finishes a task that passes the existing three checks (declared `Files:` exist, `Test command:` exits 0, git HEAD advanced) **and** an acceptance adapter resolves for the project, the agent runs the deliverable's run-smoke (`python -m <pkg> --help`); the task is marked `done` only if run-smoke succeeds. A `done` task now means "the deliverable actually ran."
2. When the same task's run-smoke **exits non-zero** (e.g. `python -m <pkg>` fails because the package is not `-m`-runnable — the diagnosed coin-flip), the task is demoted `done → failed`; partial progress is kept on disk (no silent discard), consistent with the existing failed-task behavior.
3. When the project type has **no acceptance adapter** (a non-python-cli project, or any type with no `provides_acceptance` adapter), the acceptance check is a **logged no-op** — the task's done/failed verdict falls back to the existing three checks, exactly as today (no regression for unsupported types).
4. The acceptance adapter is **resolved through the registry, never hardcoded**: `run_plan` asks the registry which adapter detects the project root and provides an acceptance contract, then binds it to the root — so adding a language (feature 5) needs no run-loop edit.
5. The acceptance run-smoke is **surfaced to the user**: the run-plan progress shows the acceptance command and its ✓/✗ result (riding the existing per-step card mechanism), and the run summary's `done` count now reflects deliverables that actually ran. No change to the TUI's layout or ergonomics.
6. The last run-smoke command + verdict are **persisted** so a resumed run knows which tasks were acceptance-verified.

### Failure paths (feature touches external I/O — subprocess + filesystem)

7. When run-smoke **exceeds the configured shell-exec timeout**, it is treated as a failure → task `failed`; the timeout value comes from existing config (no new magic number).
8. When the deliverable's package **cannot be resolved** (`resolve_pkg` raises — a python-cli project that produced no `-m`-runnable package), the task is `failed` with a clear reason recorded (`pkg-unresolvable`) — "not runnable" is exactly the failure the gate exists to catch; no new outcome status is introduced.
9. When the `bwrap` sandbox is **unavailable** (userns/AppArmor blocked) and `sandbox: auto|on`, run-smoke **degrades exactly like the existing `shell_exec`/`run_tests` path** (policy-only / refuse per `policy.py`), never crashing the run — it inherits this from the shared execution primitive, no special-casing.

## Existing behaviors this feature touches

(from `docs/user-journeys.md` Journey 5 "Run the plan autonomously (`/go`)" + `docs/architecture.md` `### Task outcome status` / `### System invariants` / the `run-plan` Product Contract)

- **The existing three machine checks must not change** — `Files:` exist, `Test command:` exit-0, per-task git HEAD advance. The 4th check is additive and runs after them.
- **`done | failed | skipped` taxonomy is unchanged** — no new outcome status; acceptance failure uses the existing `done → failed` demotion path. `_classify_outcome` is untouched.
- **Stop reasons unchanged** — `max_failures`, `plan_modified`, `all_done`, `no_tasks` still fire as before; the `TASKS.md` re-hash / plan-modified detection per iteration is preserved.
- **Auto-commit hook + per-task HEAD-advance invariant** stay; acceptance runs after the HEAD check.
- **Trust / sandbox / policy gating** is reused, not bypassed — run-smoke goes through the same `execute()` boundary as every other shell action.
- **The TUI's UX / ergonomics are preserved** — acceptance rides the existing `on_task_end` outcome and `on_tool_executed` card seam; no layout/keybinding change.
- **All existing `run_plan` tests must pass unchanged after the strangle** — the module extraction is behavior-preserving (proves no regression).

## Contracts

(internal APIs; the user-facing promise lives in the `run-plan` Product Contract `## Must not break`)

- `Skill.provides_acceptance: bool` (class attr, default `False`) — symmetric with `provides_test_runner`; `PythonCliAdapter` sets it `True`. Marks an adapter that owns an acceptance/run contract.
- `Skill.bind(root: Path) -> Skill` — default returns `self` (stateless skills); `PythonCliAdapter` returns a root-bound instance (`PythonCliAdapter(root=root)`). Polymorphic root-binding so the registry never needs to know a constructor shape.
- `SkillRegistry.acceptance_adapter(root: Path) -> Skill | None` — first **detecting** skill with `provides_acceptance` (UNFILTERED scan, like `get`/`default`/`default_runnable`, so a `hidden` adapter is eligible), returned **root-bound** via `.bind(root)`. Returns `None` when no acceptance adapter detects the root. (Resolution detects on the rootless singleton, then returns the bound instance — `acceptance_spec`/`run_smoke` are never called on the rootless one, which raises.)
- **`run_plan` verification #4** — after the existing three checks, when `acceptance_adapter(root)` is non-`None`: execute `adapter.acceptance_spec(task)`'s command via the existing `execute(..., trust="yolo", sandbox=…, shell_exec_timeout=…)` path; success keeps `done`, any failure (non-zero exit / timeout / unresolvable pkg) demotes to `failed` with the reason recorded. **Does NOT inherit `_verify_task_test_command`'s exit-4/5 leniency** — run-smoke of a finished deliverable is exit-0-or-fail.
- `AgentState` gains default-valued, forward-compatible fields for the last run-smoke command + verdict + reason (atomic persist, same shape as the v0.12.5 additions).
- **New module `code_scalpel/plan_runner.py`** — `run_plan` (and its private helpers) extracted from `agent.py` into a `PlanRunner` collaborator that `StepAgent.run_plan` delegates to. Commit 1 is a pure behavior-preserving extraction (`PlanRunner(self)`, existing tests unchanged); commit 2 adds the gate.

## Stack expectations touched

(from `docs/stack-notes.md`)

- **subprocess → git / ripgrep**: "Subprocess cwd is **pinned to the project root**" and "Use `asyncio.create_subprocess_exec` (argv list, no shell) over `create_subprocess_shell`". run-smoke executes the adapter's **argv list** (`["python","-m","<pkg>","--help"]`) with cwd = project root, via the existing `execute()` primitive — no shell string is constructed. Source: https://docs.python.org/3/library/asyncio-subprocess.html#security-considerations ; `docs/architecture.md` SC2.
- **`python -m <pkg>` invocation contract**: running a package via `-m` requires a `__main__.py`; `run_smoke` targets a `-m`-runnable package. This hinge idiom is already **execution-verified** by feature 1's `test_scaffold_smoke` — no spike needed. Source: https://docs.python.org/3/library/__main__.html#main-py-in-python-packages
- **bubblewrap (`bwrap`)**: when `sandbox: auto|on`, model-issued execution is sandboxed; "detect this failure and degrade … not crash" on userns/AppArmor block. run-smoke inherits this from the shared `execute()` path. Source: https://github.com/containers/bubblewrap/issues/324 ; `docs/architecture.md` SC3.
- **asyncio**: "Never block the event loop … offload blocking work (subprocess wait)". run-smoke is awaited through the existing async subprocess path. Source: https://docs.python.org/3/library/asyncio-dev.html#running-blocking-code

## Interaction scenarios

Shared state: the per-task loop in `run_plan` (now `PlanRunner`), `TASKS.md` (re-hashed each iteration), `STATE.json` (`AgentState`), the process-global `SkillRegistry`, the trust level, and the TUI callbacks (`on_task_end` / `on_tool_executed`).

- **When `TASKS.md` is edited mid-run while the gate is active:** the existing per-iteration re-hash still detects the change and stops with `plan_modified` — the new 4th check does not suppress or race the plan-modified detection.
- **When the project trust level is `skeptic` and a task reaches the acceptance check:** run-smoke executes at `trust="yolo"` as a **plan-owned machine check**, mirroring the existing `_verify_task_test_command` (which already runs at yolo). The command is the adapter's **code-owned, deterministic** argv (not model- or user-authored text), so no untrusted string reaches the shell. (Feature 4's model-derived acceptance commands at yolo are a separate provenance question — flagged forward, not in scope here.)
- **When a run is resumed after a crash mid-task:** the persisted run-smoke verdict/command lets the resumed run know which tasks were acceptance-verified; the new `AgentState` fields are default-valued so older `STATE.json` files load unchanged.
- **When the acceptance adapter is asked for a python project that also matches `PythonSkill`:** `acceptance_adapter` selects the `provides_acceptance` adapter (`PythonCliAdapter`), while `default_runnable_skill` is unchanged (still `PythonSkill`) — the test-runner path and the acceptance path resolve independently, no cross-interference.

## Test plan

- Existing tests that must pass: **all existing tests**, especially the entire `run_plan` suite in `tests/test_agent.py` (this is the proof the strangle is behavior-preserving) and the `skills/` + registry suites. Tests use `MockLLMAdapter` / `MockShellRunner` (`tests/mocks.py`).

- New tests:
  - `test_acceptance_gate_keeps_done_when_runsmoke_succeeds`: a task that passes the three existing checks and whose `python -m <pkg> --help` exits 0 → stays `done`.
  - `test_acceptance_gate_demotes_done_to_failed_when_runsmoke_fails`: same setup but run-smoke exits non-zero → outcome demoted to `failed`, partial progress preserved (scenario 2).
  - `test_acceptance_gate_noop_when_no_acceptance_adapter`: a project root with no `provides_acceptance` adapter → acceptance check is skipped (logged), `done` reachable via the three existing checks (scenario 3, no-regression).
  - `test_acceptance_pkg_unresolvable_fails`: python-cli project where `resolve_pkg` raises → task `failed`, reason `pkg-unresolvable` recorded, no new status introduced (scenario 8, failure path).
  - `test_acceptance_runsmoke_timeout_fails`: run-smoke exceeds the configured timeout (via `MockShellRunner`) → `failed`; verifies the timeout comes from config, not a literal (scenario 7, failure path).
  - `test_acceptance_does_not_inherit_exit_4_5_leniency`: a run-smoke exit 4/5 is treated as **failure** (unlike `_verify_task_test_command`) — guards the arch-note sharpening.
  - `test_runsmoke_executed_via_yolo_plan_owned_path`: on a `skeptic`-trust project the acceptance run-smoke still executes (plan-owned, `trust="yolo"`), mirroring test-command verification (interaction/security).
  - `test_runsmoke_command_is_code_owned_argv`: the executed command equals the adapter's argv `["python","-m","<pkg>","--help"]` (code-owned, not model-supplied).
  - `test_state_persists_runsmoke_verdict_and_reason`: `AgentState` round-trips the new run-smoke command/verdict/reason fields; an old `STATE.json` without them still loads (forward-compatible defaults) (scenario 6).
  - `test_done_count_means_ran`: after a run, every `done` task has a recorded `passed` run-smoke verdict (the `## Must not break` contract).

- Interaction scenario tests (one per Interaction scenario):
  - `test_plan_modified_still_stops_with_gate_active`: editing `TASKS.md` mid-run still yields `stopped_reason == "plan_modified"` with the 4th check enabled.
  - `test_acceptance_adapter_resolution_drives_production_registry` (**test-wiring-parity**): `SkillRegistry.acceptance_adapter(python_root)` via the **production** module-level registry returns a root-bound `PythonCliAdapter` (`provides_acceptance` True), and `default_runnable_skill(python_root)` is unchanged (`PythonSkill`); returns `None` for a project with no acceptance adapter.
  - `test_runsmoke_verdict_resumes_from_state`: a resumed run reads the persisted verdict (sets up post-crash `AgentState`, asserts acceptance-verified tasks are not re-run-smoked unnecessarily / verdict is available).

- Bind / capability unit tests:
  - `test_bind_default_returns_self`: a stateless skill's `bind(root)` returns itself.
  - `test_bind_python_cli_returns_root_bound`: `PythonCliAdapter().bind(root)` returns a root-bound instance whose `run_smoke`/`acceptance_spec` resolve `<pkg>` (no rootless raise).
  - `test_provides_acceptance_flag`: `PythonCliAdapter.provides_acceptance is True`; existing skills (`PythonSkill`, Go/JS/Docker/Postgres/SQLite) are `False`.

- Stack-spec tests (one per stack expectation; must cite the source URL in a comment, verify against the rule not the coder's mapping):
  - `test_runsmoke_uses_argv_no_shell`: the acceptance execution is built as an argv list and dispatched without a shell string (cites the asyncio-subprocess security-considerations URL).
  - `test_runsmoke_cwd_pinned_to_root`: the acceptance subprocess cwd is the project root (cites SC2).
  - (`python -m` runnability is covered by feature 1's `test_scaffold_smoke`; reference it rather than duplicate.)

## Docs to update

- `docs/architecture.md`: add an Architectural decision — **Acceptance gate (verification #4) in `run_plan`** (run-smoke the deliverable via the registry-resolved `provides_acceptance` adapter; mandatory-when-adapter-resolves, logged-no-op otherwise; default-floor only, richer specs deferred); add the **File-layout** entry for `code_scalpel/plan_runner.py`; extend `### Task outcome status` / `### System invariants` to note that a `done` task now requires run-smoke to pass where an acceptance adapter applies. Updated by `pm-architect` post-coding.
- `docs/user-journeys.md`: Journey 5 ("Run the plan autonomously (`/go`)") — update the expectation/"what can go wrong": a task is `done` only when the deliverable actually runs; a non-running deliverable now flips to `failed` instead of a false `done`. Updated by `pm-architect` post-coding.
- `docs/threat-model.md`: record that acceptance run-smoke autonomously executes the project's own (model-influenced) code through the existing trust-gated + `bwrap`-sandboxed + `policy.py`-blocked shell path at `trust="yolo"` (plan-owned) — **no new boundary**; reaffirm SC2/SC3 cover it; the floor command is code-owned/deterministic (the model-derived-command provenance question is feature 4's). Updated by `pm-architect` post-coding.
- `.ai-pm/contracts/run-plan.md`: `## Must not break` — extend "a task is `done` only if its tests pass and git HEAD advanced" to "**and** acceptance run-smoke passed (where an acceptance adapter applies)"; `## Acceptance checks` — note the `notes_cli` N≥3 outcome probe is this feature's release gate getting teeth. (Surfaced to PM; updated via the contract process.)
- `docs/plan.md`: mark v0.14 progress — the acceptance gate (✓ inline next to the relevant roadmap item). (Project working rule.)

## Out of scope

- **Task-declared `Acceptance:` field consumption + narrow-pass-derived spec + write-back** — `feat/acceptance-spec-in-tasks` (feature 4). `Task.acceptance` exists in the schema but stays **unused** here; this feature consumes only the adapter's built-in **default-floor**. Sibling of the categorical choice "how acceptance expectations are specified" (arch note Fork 2: B contract / C fallback / A floor — this feature ships A only).
- **The self-fix route-back** on acceptance failure (route the run-smoke output back to `code_with_retry` and iterate) — `feat/acceptance-self-fix-loop` (feature 3). Here, acceptance failure simply flips the task to `failed`.
- **Richer round-trip acceptance** (`add 'x' → list` shows the note) — needs a task-declared/derived spec; feature 4. The floor is `python -m <pkg> --help` exit-0 only, which is the minimum that catches the diagnosed "does not run at all" failure.
- **Other-language adapters** (`NodeCliAdapter`, Go, etc.) — `feat/node-cli-adapter` (feature 5). The resolution mechanism here is built to **allow** them with no run-loop edit, but none is implemented; `acceptance_adapter` returns `None` for those types today (scenario 3 no-op).
- **Further `agent.py` decomposition** beyond extracting `run_plan` — opportunistic later (arch note Fork 3 item 6); only `run_plan` + its private helpers move here.
- **Automated CI wiring of the `notes_cli` N≥3 outcome gate** — stays **manual** per the "outcome-driven release gate" decision; this feature is *verified by running* the probe (its acceptance criterion), not by adding a CI automation.
- **New outcome status** (e.g. `noop_done`) — explicitly not introduced; acceptance reuses `done → failed`.
