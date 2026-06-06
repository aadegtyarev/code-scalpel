# Acceptance self-fix loop — plan

Source: backend redesign migration path item 3 (`.ai-pm/arch/backend-redesign_arch.md`
§"Migration path", lines 311–314), PM-selected (`бери фичу 3`); structural rulings
in `.ai-pm/arch/acceptance-self-fix-loop_arch.md`. Decision authority: interactive
(project default); the three product forks below were resolved by the PM at planning.

## What this changes (plain language)

Today, when the agent finishes the last task of a runnable command-line project and
the finished tool **still doesn't actually run**, that task is marked **failed** and
the loop stops there. This feature gives the agent a chance to **fix it itself**: it
feeds the failing run back to the model as the error to fix, rebuilds, and runs the
tool again — up to a bounded number of attempts — before giving up. This is the
"the agent fails its own check and iterates" promise made real, and the lever toward
a *consistent* result instead of one that depends on model luck.

**PM decisions (fixed for this feature):**
1. **On by default** — self-fix runs out of the box.
2. **Trust-gated** — at `skeptic` the agent does NOT auto-fix (it fails and waits for
   the human, exactly as today); at `optimist`/`yolo` it auto-fixes.
3. **Budget = 3** self-fix attempts before the task is finally `failed`.

## Scenarios

1. **(optimist/yolo) Self-fix recovers a task.** The plan's last task is a runnable
   CLI deliverable; the finished tool fails its run-smoke. The agent re-feeds the run
   output to the model, rebuilds, and re-runs the tool. If a rebuild makes it run, the
   task ends **`done`** (it would have been `failed` before this feature).
2. **(optimist/yolo) Budget exhausted → failed.** The run-smoke keeps failing across
   all 3 self-fix attempts; after the budget is spent the task is finally **`failed`**
   (same terminal state as today, just reached after bounded retries).
3. **(skeptic) No auto-fix.** At `skeptic` trust, a failing final-task run-smoke marks
   the task **`failed`** immediately and leaves it for the human — **unchanged from
   today**. The agent never silently rebuilds at skeptic.
4. **Self-fix off → today's behavior.** With the self-fix knob turned off, a failing
   applicable final-task run-smoke is marked `failed` immediately — the feature-4
   behavior, restorable by config.
5. **Only the last applicable task is self-fixed.** Self-fix fires under the *same*
   three-signal gate that governs demotion (intent × position × state). An **early**
   task still building toward the CLI, a **library** / no-CLI project, and a **no-spec**
   project are **observed, never self-fixed and never demoted** — the load-bearing
   no-regression invariant, unchanged.
6. **Language-agnostic.** Self-fix works for any project type the adapter detects — the
   run command and the failure signal come only from the `detect()`-selected adapter.
   `notes_cli` (python) is the proof, not the target; zero language strings live in the
   run loop or the self-fix path.
7. **Anti-loop early stop.** If a rebuild changes nothing observable (the re-run produces
   byte-identical output to the previous attempt), the agent stops early instead of
   burning the rest of the budget, then marks the task `failed`.

### Failure paths (feature touches external I/O — shell run-smoke + file-writing rebuilds)
8. **Rebuild engine raises mid-self-fix.** If `code_with_retry` raises during a self-fix
   attempt, the loop treats that attempt as failed, does not crash the run loop, and the
   task ends `failed` (partial progress kept on disk, per the existing run-loop contract).
9. **Re-run-smoke errors (timeout / refused / non-zero).** A self-fix attempt whose
   re-run-smoke times out, is policy-refused, or exits non-zero counts as a failed
   attempt; its output is the signal for the next attempt (or, if identical, triggers the
   scenario-7 early stop).

## Existing behaviors this feature touches

(from `docs/user-journeys.md` Journey 5 + `.ai-pm/contracts/run-plan.md` — what must not break)
- **Per-task git HEAD must advance or the task is `failed`** — each self-fix rebuild must
  re-snapshot HEAD and the HEAD-advance check must be re-evaluated per attempt, not carried
  stale across attempts.
- **The acceptance gate never false-fails** — early CLI tasks, libraries, and no-spec
  projects stay observational (never demoted, now also never self-fixed).
- **The loop stops after N consecutive failures and keeps partial progress on disk** —
  self-fix is bounded and does not bypass or reset the consecutive-failure stop.
- **Auto-commit on done** — a task recovered by self-fix is committed like any other
  `done` task (auto-commit hook commits if the model forgot).
- **Editing `TASKS.md` mid-run stops the loop** — self-fix lives within a single task's
  execution and does not interfere with the between-tasks plan-modified check.
- **Status taxonomy unchanged** — no new task-outcome status; self-fix reuses the existing
  `done → failed` edge, deferred until the budget is exhausted.

## Contracts

(new config keys — pydantic `AgentConfig`; the failure-signal carrier is internal)
- `acceptance_self_fix: bool = True` — master on/off for the self-fix loop. Default **on**.
- `acceptance_self_fix_max_attempts: int = 3` — bounded self-fix attempts before final
  `failed`. Default **3**.
- (no new temperature knob — self-fix reuses `code_with_retry`'s existing code-mode
  temperature; KD7.)
- **Internal (not a public/config contract):** the failing run-smoke output is carried
  **inline** on the returned `TaskOutcome` (a new optional field, default `None`,
  preserved by `_demote`'s field copy) — it is NOT persisted to `STATE.json` (KD2). The
  trust gate reuses `policy.auto_confirm(trust)` (already `optimist`/`yolo` ⇒ True; KD3).

## Stack expectations touched

(from `docs/stack-notes.md` — rules the new config fields must respect)
- **Pydantic v2**: config fields are declared on the `BaseModel` with literal defaults
  (no magic numbers anywhere but `config.py`); validators (if any) use `@field_validator`,
  config via `model_config = ConfigDict(...)` — not v1 `class Config` / `@validator`.
  Source: https://docs.pydantic.dev/latest/concepts/models/ and
  https://docs.pydantic.dev/latest/concepts/validators/
- **asyncio**: the self-fix loop is on the async run-loop path; all I/O (rebuild, re-run-
  smoke) stays awaited — no synchronous blocking call introduced on the event loop.
  Source: https://docs.python.org/3/library/asyncio-dev.html#running-blocking-code

## Interaction scenarios

This feature is **not** provably isolated — it adds an outer loop over the shared
build→verify sequence (`code_with_retry` then `verify_task`), drives shell run-smoke and
file-writing rebuilds, and shares the run-loop's git HEAD state and the auto-commit hook.

- **When a self-fix rebuild runs while the per-task HEAD-advance check is active:** each
  attempt must re-snapshot `head_before` so the HEAD-advance check passes/fails on *that*
  attempt's commit, never a stale prior sha. A recovered task ends with HEAD advanced.
- **When self-fix nests over `code_with_retry`'s own internal test-retry loop:** the two
  budgets are independent — outer self-fix (3) × inner `code_with_retry` (1 +
  `max_debug_attempts`). The combined worst case is ~9 build passes on the *one* last
  applicable task per plan (KD8). Accepted and documented; self-fix fires at a single
  position (`should_run_now`) so the multiplier applies at most once per plan.
- **When a self-fix attempt succeeds and the auto-commit hook runs:** the recovered task
  is committed exactly like a first-pass `done` task — no double-commit, no skipped commit.

## Test plan

- **Existing tests that must pass:** all existing tests. Specifically
  `tests/test_acceptance_enforcement.py` is **unaffected** — it calls `verify_task`
  directly, and self-fix lives in the run loop (`_run_task`), not in `verify_task`
  (KD1), so the verifier's demotion contract is unchanged.
- **Anticipated necessary existing-test change (justify each in the commit):** any
  *run_plan-level* test that drives a full loop to a failing final-task run-smoke **at
  optimist/yolo trust** will now trigger self-fix instead of an immediate `failed`. Where
  found, the coder either pins that test's trust to `skeptic` (preserving immediate-fail
  semantics) or extends its mocks to cover the bounded self-fix attempts — each change
  justified as a feature-3 contract consequence, not a silent edit. No test assertion is
  weakened to hide a regression.

- **New tests** (new file `tests/test_acceptance_self_fix.py`, mirroring the `_agent` /
  `_config` / `MockLLMAdapter` / `MockShellRunner` fixtures of `test_acceptance_enforcement.py`):
  - `test_self_fix_recovers_task`: optimist; applicable + last task; run-smoke fails then
    passes after one rebuild → final status `done` (given a failing-then-passing shell
    sequence, when the loop runs the task, then the task is recovered to `done`). Drives the
    **production `_run_task` / run-loop path** (test-wiring-parity).
  - `test_self_fix_budget_exhausted_then_failed`: optimist; run-smoke fails on every attempt
    → status `failed` after exactly 3 self-fix attempts; assert `code_with_retry` was
    re-invoked the budgeted number of times (not more, not fewer).
  - `test_skeptic_no_autofix`: skeptic; applicable + last + failing run-smoke → status
    `failed` and `code_with_retry` is invoked only for the initial build, never re-invoked
    (the trust gate is a machine check — verifies `policy.auto_confirm` path).
  - `test_self_fix_off_restores_immediate_failed`: `acceptance_self_fix=False`; failing
    applicable final-task run-smoke → immediate `failed`, no rebuild (feature-4 behavior).
  - `test_identical_run_smoke_output_breaks_early`: run-smoke output byte-identical across
    two attempts → loop stops before the full budget is spent (fewer rebuilds than 3), task
    `failed` (the anti-loop guard).
  - `test_early_task_never_self_fixed`: applicable spec but NOT `should_run_now` (early task)
    → observed, no self-fix, no demotion (unchanged no-regression).
  - `test_library_never_self_fixed`: not-applicable (floor/library) spec → observed, no
    self-fix, no demotion (load-bearing no-regression invariant).
  - `test_self_fix_signal_reaches_builder`: assert the failing run-smoke output is what is
    handed to `code_with_retry` on the retry (the inline-signal wiring of KD2 actually
    flows; not just that a retry happened).
  - `test_self_fix_code_with_retry_raises`: `code_with_retry` raises during a self-fix
    attempt → run loop does not crash, task ends `failed`, partial progress preserved
    (failure path 8).
  - `test_self_fix_run_smoke_timeout_attempt`: a self-fix attempt's re-run-smoke times out /
    is refused → counts as a failed attempt, its output feeds the next attempt (failure
    path 9).

- **Interaction scenario tests:**
  - `test_head_resnapshotted_each_self_fix_attempt`: a self-fix rebuild that advances HEAD
    is accepted on its own attempt; the HEAD-advance check is evaluated against the current
    attempt's commit, not a stale prior sha.
  - `test_recovered_task_is_committed`: a task recovered by self-fix is committed via the
    auto-commit-on-done hook exactly once.

- **Stack-spec tests** (one per stack expectation):
  - `test_self_fix_config_defaults`: `AgentConfig().acceptance_self_fix is True` and
    `AgentConfig().acceptance_self_fix_max_attempts == 3` — the defaults live in `config.py`
    (pydantic field defaults; no magic numbers in the loop). Ref:
    https://docs.pydantic.dev/latest/concepts/models/
  - `test_self_fix_language_agnostic`: with a **non-python** mock adapter (the generality
    pattern from feature 4's non-python adapter test), the self-fix path runs using the
    adapter-provided command and contains **no python/`-m`/`notes_cli` literal** in the run
    loop or retry-prompt assembly — verifies the run-loop is adapter-driven, not
    python-shaped. Ref: `docs/architecture.md` §"ProjectAdapter".

## Docs to update

(coder does not touch docs; `pm-architect` updates the doc-owned files on the post-coding
handoff; the orchestrator updates the contract)
- `docs/user-journeys.md`: Journey 5 step 3 + Invariants — at `optimist`/`yolo` the agent
  now tries to fix a failing final-deliverable run automatically (bounded) before failing;
  at `skeptic` it fails and waits for the human. (pm-architect.)
- `docs/architecture.md`: new decision record **"Acceptance self-fix loop (feature 3)"**;
  update §"Task outcome status" (the `done → failed` edge is now *deferred through the
  bounded self-fix budget* at optimist/yolo); add the new **`SCn`** for the bounded
  autonomous self-fix loop in §"Security constraints"; note in §"File layout" that
  `plan_runner.py` gains the self-fix orchestration helper. (pm-architect.)
- `docs/threat-model.md`: revisit per the document's own Review trigger ("the trust model
  changes / a new auto-resolution path lands"). Update **T05/T06** (autonomous loop — the
  bounded self-fix loop is a new autonomous iteration surface, mitigated by budget +
  identical-output break + trust gate) and **T10** (wrong auto-resolution — auto-fixing at
  optimist/yolo is a new place the model acts without per-step confirm; skeptic-no-autofix
  is the mitigation); add the `SCn` reference; bump `Last reviewed`. (pm-architect.)
- `.ai-pm/contracts/run-plan.md`: add a `## Must work` line for the trust-gated bounded
  self-fix loop; **remove** the Out-of-scope deferral line (90–92) for "model self-fixing of
  mid-plan failures"; update the `## Acceptance checks` bound (the gate now *self-fixes
  before* the final demotion at optimist/yolo). (orchestrator, at handoff.)
- `docs/plan.md`: mark feature 3 progress with `✓` in the §31 roadmap. (pm-architect, on
  the doc handoff.)

## Out of scope

- **A fuller "deliverable complete" signal** that enforces a runnable CLI built by an
  *earlier* task when the final task is non-CLI — still deferred (contract Out-of-scope);
  self-fix fires only at the last applicable task, same gate as the demotion.
- **Acceptance run-smoke for setuptools flat-layout projects** — `resolve_pkg` is
  src-layout/hatchling only; flat-layout still skips run-smoke (separate reach gap).
- **A second language adapter** (node-cli) — that is feature 5; this feature proves
  language-agnosticism via the existing PythonCliAdapter + a non-python mock-adapter test,
  not a real second adapter.
- **Sibling trust levels handled differently than the PM decision** — `skeptic` =
  no-autofix, `optimist`/`yolo` = autofix is the full set for this feature; no new
  trust level, no per-level budget. (Categorical: "trust level" — the full existing set is
  covered by the gate; no sibling left implicitly chosen.)
- **A new task-outcome status** for "recovered by self-fix" — reuses `done`; not a new
  taxonomy value.

## Key design decisions

- **KD1 — Loop home: `plan_runner._run_task` (arch Q1-B).** `verify_task` stays a pure
  Definition-of-Done reporter; the run loop (which already owns the build→verify edge)
  orchestrates build → verify → rebuild → re-verify. Rejected: wiring it inside
  `verify_task`, which would invert the reporter→builder dependency.
- **KD2 — Failure signal carried inline on `TaskOutcome` (arch Q2-A).** New optional
  field, default `None`, preserved by `_demote`. NOT persisted to `STATE.json` (it is a
  within-turn signal; resume re-derives + re-runs smoke). Avoids unbounded state bloat.
- **KD3 — Trust gate = `policy.auto_confirm(trust)` (machine check).** Skeptic → no
  auto-fix, record `failed`, stop — never a prompt instruction.
- **KD4 — Budget + on/off in `config.py` (pydantic).** Default on, budget 3 — no magic
  numbers in the loop.
- **KD5 — One outer anti-loop guard:** identical re-run-smoke output two attempts in a row
  ⇒ stop early (analogue of `_build_failure_retry_prompt`'s identical-`test_output` break).
  No hypothesis guard at this layer (that lives inside `code_with_retry`).
- **KD6 — No new task-outcome status:** reuse the existing `done → failed` edge, deferred
  until the budget is exhausted.
- **KD7 — No new temperature knob:** self-fix reuses `code_with_retry`'s code-mode
  temperature; keeps the config surface minimal.
- **KD8 — Combined bound accepted + documented:** outer self-fix (3) × inner
  `code_with_retry` (1 + `max_debug_attempts`) ≈ up to 9 build passes worst case, on the
  *one* last applicable task per plan. Accepted because self-fix fires at a single position.
- **KD9 — Language-agnostic:** the retry prompt is assembled from the adapter-provided
  command + the run-smoke output only; zero language strings in `plan_runner` / the
  self-fix path.
- **KD10 — `_run_task` extraction:** the self-fix cycle is extracted into a private helper
  on the runner to keep `_run_task` under the 50-line function minimum.

## Definition of Done

- All 7 scenarios + 2 failure paths implemented; all new + interaction + stack-spec tests
  green; full pipeline green (`pytest`, `ruff check .`, `ruff format --check .`,
  `mypy code_scalpel/`).
- New code ≥80% covered; new file ≤300 lines, new/changed functions ≤50 lines, cyclomatic
  ≤10; tests written with the code.
- No language strings in the run loop / self-fix path (audited per KD9).
- Docs-to-update handoff complete (pm-architect: user-journeys, architecture, threat-model,
  plan.md; orchestrator: run-plan contract).
- **Feature acceptance (Step 5.5, before ship):** a live `notes_cli` outcome probe shows
  self-fix recovering a failing final-task build at optimist/yolo and converging toward a
  **stable 3/3 task_solved** — the consistency lever this feature exists for.
