# acceptance-spec-in-tasks — review

<!-- Pass-1 plan-compliance will be prepended by pm-plan-checker after the doc handoff. -->

## Plan compliance (Pass 1 — pm-plan-checker, re-checked 2026-06-06 incl. timing fix `1929ce0`)

Verdict against the post-review plan (`docs/features/acceptance-spec-in-tasks_plan.md`) + the timing-fix arch section (`.ai-pm/arch/acceptance-spec-in-tasks_arch.md` `## Timing fix (post-probe)`). The prior Pass-1 was `approve` on the pre-timing-fix code; this re-check covers the three-signal demotion fix introduced after the live probe proved the gate never enforced on greenfield.

### Original plan scenarios (all still implemented + tested)

- ✓ Scenario 1 (declared/applicable spec enforces — demote on fail) — `plan_verify.py:189` (`if applicable and should_run_now and not ok`); tests `test_enforce_on_derived_applicable_spec`, `test_expected_observable_enforced_on_applicable`.
- ✓ Scenario 2 (no-declared → derive args-only, write back, enforce if applicable) — `plan_loading._derive_acceptance` + `_derive_specs_for_tasks`; tests `test_enforce_on_derived_applicable_spec`, `test_derived_spec_written_back_not_rederived`.
- ✓ Scenario 3 (not-applicable / floor-only → observational, NOT demoted — load-bearing no-regression) — gate at `plan_verify.py:189`; floor `applicable=False` lock; tests `test_observational_when_derivation_not_applicable` (real library shape), `test_floor_only_is_observational`, and now `test_library_still_never_demoted_at_last_task`.
- ✓ Scenario 4 (write-back, deterministic next run) — `_persist_derived_tasks`; tests `test_derived_spec_written_back_not_rederived`, `test_derived_spec_resumes_from_plan`.
- ✓ Scenario 5 (args-only, adapter-built argv, no free-form shell) — narrow pass returns `{applicable,args,expected}`; adapter builds argv via `run_smoke`; `shlex.join(shlex.split(...))`; tests `test_derived_command_is_args_only_adapter_built`, `test_acceptance_command_argv_no_shell`.
- ✓ Scenario 6 (run-loop language-agnostic) — verify path reads only `spec.applicable` ANDed with the structural `should_run_now`; no language string; test `test_run_loop_enforces_through_a_nonpython_adapter` (now also drives the last-task enforcement path AND the early-task observe path through a non-python adapter).
- ✓ Scenario 7 (non-empty `expected` must appear) — `plan_verify.py`; test `test_expected_observable_enforced_on_applicable`.
- ✓ Scenario 8 (notes_cli 3/3 via derived path) — manual outcome probe (Step 5.5). The pre-timing-fix probe scored 7,7,4 (gate never engaged on greenfield — root cause documented in the arch `## Timing fix`); the re-probe after the fix confirmed derivation marks CLI tasks applicable=true and enforcement targets the final task. The N≥3 `task_solved` outcome gate remains a Step-5.5 manual probe to re-run before ship.
- ✓ Failure path 9 (derivation fails → floor, observational, no crash) — `test_derivation_failure_falls_back_observational`.
- ✓ Failure path 10 (write-back fails → in-memory, no corruption) — `test_writeback_failure_uses_inmemory_and_logs`.
- ✓ Failure path 11 (applicable timeout/non-zero → demote with reason; timeout from config) — `_failure_reason` + `shell_exec_timeout` (no magic number); covered via `test_enforce_on_derived_applicable_spec` / `test_last_task_enforces_when_applicable`.
- ✓ Failure path 12 (pkg-unresolvable: applicable demotes, not-applicable observes) — `test_applicable_pkg_unresolvable_demotes_vs_notapplicable_observes`, `test_pkg_unresolvable_recovers_source_for_derived`.

### Timing fix (post-probe) — three-signal demotion (spawn verification points 1–4)

The probe proved the pre-loop derivation, run on an empty greenfield fixture, marked every task `applicable=false` ("no runnable CLI") and persisted that as a permanent marker — enforcement was structurally disabled. The fix separates **intent** (pre-loop, text-only), **position** (`should_run_now`, plan structure), and **state** (verify-time run-smoke). Verified against the arch `## Timing fix` and the code:

- ✓ **(1) Demotion is exactly `applicable and should_run_now and not ok`.** `plan_verify.py:189` (`if applicable and should_run_now and not ok: return _demote(outcome)`), matching arch §"Timing fix" Q1/Q2 and seam 3 verbatim. The three named-case tests assert the full truth table:
  - applicable-but-early (`should_run_now=False`) → **observe** (stays done): `test_early_task_not_demoted_even_if_applicable` (failing run-smoke, not last task → done).
  - applicable + last task + broken → **demote**: `test_last_task_enforces_when_applicable`.
  - applicable + last task + runnable → **stays done**: `test_last_task_passes_when_runnable`.
  - not-applicable (library) even at last task + failing → **observe** (regression lock holds): `test_library_still_never_demoted_at_last_task` (intent=false short-circuits before position/state).
- ✓ **(2) The four invariants still hold.** Args-only: model still emits `{applicable,args,expected}`, adapter still builds argv via `run_smoke`, `test_acceptance_command_argv_no_shell` / `test_derived_command_is_args_only_adapter_built` unchanged-green. No language string in the run-loop verify path: `should_run_now` is a pure plan-index predicate (`_last_not_done_index` in `plan_runner.py`), no language knowledge; `test_run_loop_enforces_through_a_nonpython_adapter` updated for the last-task path AND adds the early-task observe assertion through the same fake non-python adapter. Library no-regression: locked by `test_library_still_never_demoted_at_last_task` + `test_observational_when_derivation_not_applicable`. Observational-where-not-applicable: preserved and *extended* (not-applicable observes AND applicable-but-early observes) — the noop-never-applicable assertion (`plan_verify.py`) is unaffected.
- ✓ **(3) The derive prompt now judges INTENT not state (root-cause fix).** `prompts/derive_acceptance.md` Q1 re-scoped from "**Is there** a runnable command-line deliverable here?" to "**Is this task's deliverable MEANT to be** a runnable command-line program?" with the explicit "do NOT assume the code already exists … a from-scratch build of a CLI is still `applicable: true`." This is the single change that fixes the dominant greenfield failure mode (the permanent `applicable: false` write-back). Adapter unchanged (stays position-unaware + language-agnostic — arch seam 5). Card string fixed (`plan_loading.py` — `runnable CLI (enforced at final task)` / `observed (library / not a CLI)`).
- ✓ **(4) All earlier scenarios/tests still pass; nothing out-of-scope touched.** No self-fix route-back (feature 3) — demotion is a status flip, subscribes to nothing. No Node adapter (feature 5) — the fake non-python adapter in the test proves generality without shipping one. The position signal is purely additive (a new keyword arg threaded `plan_runner → verify_task → _verify_acceptance`, default `False` — the call site is the only caller). The timing-fix diff is traceable line-for-line to the arch §"Timing fix" seam changes 1–5; no cosmetic/unrelated hunks.

### KD / interaction / stack / contract (carried from prior Pass-1, re-confirmed)

- ✓ KD1/KD2/KD2b/KD3 hold (args-only json_schema, intent-gated enforcement, prose-B-as-hint, no language string in the loop).
- ✓ Interaction scenarios: write-back not flagged `plan_modified`; both pre-passes compose; resume reads written-back spec; runs at yolo on skeptic; demotion produces the feature-3 signal cleanly (no route-back). Tests `test_writeback_not_flagged_as_plan_modified`, `test_annotation_and_derivation_compose`, `test_derived_spec_resumes_from_plan`, `test_acceptance_runs_at_yolo_on_skeptic_project`, `test_pkg_unresolvable_recovers_source_for_derived`.
- ✓ Stack expectations: json_schema structured output, subprocess argv/no-shell (cites asyncio-subprocess URL), `python -m <pkg>` adapter argv, bwrap/execute() boundary — all unchanged by the timing fix (intent/position move; the execution boundary does not).
- ✓ Test-wiring-parity: `test_enforce_on_derived_applicable_spec` and the generality test drive the production `PlanRunner`/registry/`acceptance_adapter` path; the `should_run_now` signal is computed by the production `run_plan_inner` loop (`_last_not_done_index`), not hand-built in the gate.

### Pipeline (re-run this turn)

- ✓ `pytest` — **1282 passed / 40 skipped** (matches the spawn's claim; `tests/test_acceptance_enforcement.py` 33 passed).
- ✓ `ruff check .` — All checks passed. `ruff format --check .` — 195 files already formatted.
- ✓ `mypy code_scalpel/` — the lone `tools/files.py:8` unused-ignore is a pre-existing env-stub artifact; confirmed **NOT** in this diff (`git diff` over the timing-fix range and the whole feature branch shows `tools/files.py` untouched). Touched files type-clean.
- ✓ Advocate `clean` (`.ai-pm/reviews/acceptance-spec-in-tasks_advocate.md`).

### Docs-to-update — timing-change delta PENDING (flagged, not a sole-blocker per spawn)

The timing-fix commit `1929ce0` + arch design `a24ef16` landed the **design** (arch `## Timing fix`) and the **state file** — but the public docs/contract still describe the **pre-timing-fix** model ("enforces where an applicable spec exists; a failing run-smoke demotes") with **no position/final-task qualifier and no intent-vs-state distinction**:

- `.ai-pm/contracts/run-plan.md` `## Must work` (~:29-30) / `## Must not break` (~:40-43) / `## Acceptance checks` (~:62): "demotes on an applicable spec failure" — now inaccurate: an applicable spec failing on an **early** (not-last) task is **observed, not demoted**. The new "early-task-not-demoted (case c)" guarantee and the intent-vs-state framing are absent.
- `docs/architecture.md` (~:125-131, the v0.14 acceptance decision): describes "enforcing where an applicable spec exists" without the final-task position gate.
- `docs/user-journeys.md` Journey 5: same gap.

Per the spawn's explicit instruction this is **not a sole blocker** — the doc/contract delta is the pm-architect doc handoff scheduled NEXT and will land before ship; the arch `## Timing fix` §"What this section does NOT change" already names the new Must-not-break case (c) the contract must add. **This is surfaced as a verify-before-ship item, not a hard block.** It is recorded as a product note so the PM/orchestrator does not lose it: the contract MUST gain the early-task-observe guarantee before merge, or the contract will under-describe the shipped behavior.

## Definition of Done
- [x] All plan scenarios implemented and tested
- [x] Interaction scenarios have concurrent-state tests
- [x] Stack expectations respected; stack-spec tests pass
- [x] Product Contract honored; Acceptance checks pass; no silent behavior change (the timing fix narrows the demoting surface — early-task false-demote becomes observe — a strict no-regression refinement; contract text-update pending, see Docs note)
- [x] Pipeline green (pytest 1282 passed / 40 skipped; ruff check + format clean; mypy clean cacheless on touched files — `tools/files.py:8` is a pre-existing env-stub artifact NOT in this diff)
- [x] State file updated (`.ai-pm/state/current.md`, updated in `1929ce0`)
- [x] Product Impact Report present (contract touched; Pass-2 trail + advocate cover impact)
- [ ] Docs updates landed — **timing-change delta PENDING** (architecture.md / user-journeys.md / `run-plan.md` contract still describe the pre-position-gate model; pm-architect doc handoff is the scheduled NEXT step, lands before ship). Not a sole-blocker per the spawn; flagged as verify-before-ship.
- [x] Expected artifacts exist (plan, this review, contract — feature is user-facing)
- [x] Product-readiness gate resolved (user-facing — advocate `clean`)
- [n/a] Validation gate (software-kind project — code Pass-2 applies)
- [x] Failure-inventory negative-space tests present (failure paths 9-12 each have a negative-space test)

**DoD: pass (with one open item — the docs-delta handoff, scoped by the spawn as land-before-ship, not a Pass-1 hard block)**

## Blocking
None. The implementation matches the plan + the timing-fix arch section exactly; the three-signal demotion algebra, all four invariants, the intent-re-scope, and the pipeline are verified green.

## Notes (product)
1. **The timing fix narrows the demoting surface — confirm the contract follows.** Under the new code an *applicable* acceptance spec that fails on an **early** (not-last) task is now **observed, not demoted** — only the final task with a broken applicable CLI demotes. This is the intended greenfield fix (an early task whose deliverable isn't built yet must not be false-failed), and it strictly *reduces* false failures vs. the prior code. But the user-facing contract (`run-plan.md`) and `docs/architecture.md` / `docs/user-journeys.md` still say "a failing run-smoke demotes where applicable" without the final-task qualifier. The pm-architect doc handoff (NEXT) must land the early-task-observe guarantee (arch `## Timing fix` case c) into the contract before ship. Why it matters: until the contract is updated, it under-describes the shipped behavior — a reader would expect any applicable failure to demote, but mid-plan failures now (correctly) observe.
2. **Derivation now judges intent from task text, not filesystem state.** The acceptance derivation fires one LLM pass per acceptance-less task at every `/go` and marks `applicable` from the task's *intent* (a greenfield CLI build is `applicable: true` before any code exists). This is the root-cause fix for the probe's 7,7,4 (the gate never engaged on empty repos). Carries forward the prior note: the derived args are model-influenced (args-only), surfaced via the pre-loop card, and editable in the plan before first run. Why it matters: the PM should know enforcement now engages on greenfield builds at the final task, where it had no teeth before — the v0.14 `notes_cli` 3/3 gate is only meaningful with this fix in place.

## Verdict
approve

<!-- The trail below is the ONE review section the orchestrator owns, not pm-plan-checker.
     See the "Edit-ownership rule" in `workflow/enforcement.md` — the Pass-2 code-review
     trail is the single carve-out to "orchestrator does not edit content artefacts". -->
## Code review findings
Pass-2 technical review (code-review skill, high effort: 7 finder angles → verify). **Security (args-only) verified SOLID** — `shlex.join(shlex.split(...))` neutralizes every metacharacter payload (`add; rm -rf ~`, `$(whoami)`, backticks, `&&`, `|`, `>`, newlines); the verb is always code-owned `run_smoke`; only args are model/human-influenced and tokenized; the tuple→`AcceptanceSpec` migration has no stale consumers. The PM's args-only decision is correctly enforced.

### Blocking (fix before ship)

1. **Composition data-loss: the two pre-passes corrupt the typed plan on disk.** `_annotate_plan`'s *change-path* re-parses its output via `parse_tasks_md` (`plan_loading.py:167`), which drops ALL typed `Task` fields (`goal`/`files`/`acceptance`/`test_command`) — the "finding 7" trap, only fixed on the no-change path in feature 2. The new `_derive_acceptance` then (a) runs `derive_acceptance_args` on those stripped tasks → derives from title alone (empty goal/files → wrong/empty args, persisted as a marker and never re-derived), and (b) `serialize_tasks_json(new_tasks)` writes the emptied `goal`/`files`/`test_command` back to TASKS.json — **permanently destroying the user's typed plan**. Fires when both gates are true (fresh JSON plan, no skills + no acceptance — the common case). **Fix:** the annotation change-path must preserve typed fields (merge derived skills into the typed tasks, not re-parse markdown), and derivation must run on full typed tasks and never persist a field-stripped plan.

2. **Human-declared (B) acceptance breaks prose tasks and is exit-0-only.** `_declared_spec` (`python_cli_adapter.py:161-166`) space-joins ALL human acceptance bullets and routes them through `run_smoke(args)` as argv, AND hardcodes `expected=""`. Human acceptance bullets are PROSE ("the note appears in the list"), not CLI args → the loop runs `python -m <pkg> the note appears in the list`, the CLI errors, the spec is forced `applicable=True`, and the task is **demoted `done→failed` every run**. There is no structured declared-args data shape today (`Task.acceptance` is free-prose `tuple[str]`). **Resolution (orchestrator, autonomous — derivable from the no-regression principle + args-only):** in THIS feature, human-declared prose is NOT executed as argv — it is recorded and may feed the derivation as a hint; enforcement uses the derived (C, args-only) or floor (A) spec. Direct enforcement of a *structured* declared spec is deferred to a follow-up (the prose→args data shape isn't there). The binding requirement: **a task with prose acceptance must never be false-demoted.** notes_cli (no human acceptance) is unaffected — it uses C. Plan/contract updated to reflect B = hint, not direct-enforce, this iteration.

3. **`pkg-unresolvable` path drops `source` and `expected`.** When `acceptance_spec` raises (resolve_pkg / argv-assembly), `plan_verify.py:219` returns `source=None` even for a derived/declared task, and the expected-observable check is skipped. Feature-3's self-fix keys off `source`; losing it on exactly the failure path it most needs is wrong. **Fix:** recover `source` (and applicability) from the task on this path, consistent with the normal path.

### Should-fix (same pass)

4. **A prefix-shaped-but-undecodable marker wedges the task.** A `derived-acceptance:`-prefixed line with malformed JSON decodes to `None` → `_derive_specs_for_tasks` skips re-derivation (acceptance non-empty) AND `_declared_spec` treats it as declared args → enforces garbage forever, no path back to derive/floor. **Fix:** an undecodable marker is treated as absent (re-derive) or floor — never as declared args.
5. **Malformed args quoting mislabeled `pkg-unresolvable`.** `shlex.split` raising on unbalanced quotes in args is caught by the `except ValueError` meant for `resolve_pkg`, so a derived/declared arg-quoting error is reported as `pkg-unresolvable` (wrong cause) and demotes. **Fix:** separate arg-build/shlex errors from resolve_pkg errors; a malformed derived spec should fall back (not demote a healthy package).
6. **Unify the dual-source applicability.** `_task_acceptance_applicable` (`plan_verify.py:253`) re-derives the same precedence rule the adapter encodes in `AcceptanceSpec.applicable`. They agree today but can silently diverge on a future tier change (only when `resolve_pkg` raises — environment-dependent). **Fix:** expose applicability without building the command (e.g. an adapter `acceptance_applicable(task)` that doesn't call `run_smoke`/`resolve_pkg`), so there is ONE source.

### Non-blocking cleanups
7. `derive_acceptance_args` `except (Exception, json.JSONDecodeError)` — the second clause is dead (subclass), and the broad catch silently swallows a *wholesale* derivation outage (LLM down → every task floors → "no enforceable specs" reads as "no CLI here"). Surface a systematic-outage signal; drop the dead clause.
8. The noop-never-demotes invariant is load-bearing but enforced only by the two current return sites, not the gate (`if applicable and not ok`). Document/assert it.
9. Marker = JSON-in-`tuple[str]` smell (vs a typed `Task` field) — acceptable for scope, but every `task.acceptance` consumer is one missed `decode` from leaking `derived-acceptance:{...}` into UI/argv.
10. Derivation = one LLM pass per acceptance-less task (N serial passes at plan startup on a weak local model) — acceptable for scope; note the latency.
11. `auto_derive_acceptance` defaults `True` (LLM call + auto-rewrites TASKS.{json,md} on every `/go`) — consistent with the existing `auto_annotate_plan` precedent; surfaced as a UX note, not a defect.

**Orchestrator decision:** 1–3 block ship; 2 resolved autonomously toward the safe behavior (B = hint, not direct-enforce, this iteration — announced to PM). 4–6 should-fix bundled in; 7–11 cleanups. All routed to `pm-coder`. The notes_cli 3/3 outcome probe (the feature's acceptance criterion) runs at Step 5.5 before ship.

## Code review: 2026-06-06 — passed

All findings closed in fix commit `949611f` (verified):
- **1 (data-loss):** `_merge_annotated_skills` merges LLM skills into the typed tasks tuple — both annotation paths now preserve goal/files/acceptance/test_command; derivation runs on full typed tasks; no field-stripped plan is persisted. (Also fixes the pre-existing annotation change-path bug.)
- **2 (prose B):** human-declared prose is no longer executed as argv — it feeds derivation as a hint; enforcement is derived (args-only) or floor only. No false-demote of prose-acceptance tasks.
- **3 + 6:** single applicability source (`acceptance_applicable`) used by the normal and pkg-unresolvable paths; `source` recovered on failure (feature-3 provenance).
- **4:** undecodable marker re-derives (not treated as declared args). **5:** malformed args → distinct reason (`malformed-args`), not mislabeled `pkg-unresolvable`. **7:** dead JSONDecodeError clause dropped + wholesale-outage surfaced. **8:** noop-never-applicable asserted.

Security args-only invariant preserved; generality (no language string in the run-loop verify path) preserved. Pipeline green: pytest 1278 passed / 40 skipped (the single `test_app.py::test_slash_map_mounts_tool_use_card` failure on the first run was a flaky async-TUI test — green on re-run + passes in isolation + HEAD full suite green); ruff check + format clean; mypy clean cacheless (incl. `tools/files.py:8` — not flagged this run).

### Timing-fix delta (post-probe, commits 1929ce0/a24ef16) — reviewed + re-probed

The live notes_cli probe (caa564f) proved the gate NEVER enforced on greenfield: pre-loop derivation on an empty fixture marked every task `applicable: false`. Root cause: the derivation conflated intent ("meant to be a CLI?") with state ("does a runnable CLI exist now?") — always false on an empty repo. Fix = three-signal demotion `applicable (intent, pre-loop from plan text) AND should_run_now (position — last not-done task) AND not run_smoke_ok (state, verify-time)`.

Reviewed (focused, commit 1929ce0): **substantially correct, NO false-demotes.** `should_run_now` (last-not-done index) sound across edge cases (all-done short-circuited, single task, trailing-done excluded, skipped/failed-non-final never marked). Re-probe (a24ef16): derivation now marks CLI tasks `applicable: true` and targets the final task — derivation root-cause fixed. Scores 6,6,7 (still not 3/3) because the runs die at `max_failures` mid-plan (model fails T004/T005 before the final task) and `resolve_pkg` doesn't handle setuptools flat-layout (run-smoke skips) — both OUTSIDE this feature's mechanism (feature 3 self-fix + a resolve_pkg reach fix). PM decision: ship feature 4 as the correct gate-mechanism increment; 3/3 is feature 3.

Findings:
- **F1 (should-fix → addressed):** no loop-level test drove `should_run_now` through the real `PlanRunner` (all enforcement tests passed it by hand); a refactor recomputing the index inside the loop would silently false-demote early tasks. Loop-level test added.
- **F4 (should-fix → addressed):** the STATE→INTENT prompt rescope deleted the "when in doubt prefer false" hedge → wider `applicable` over-marking (a library-described-as-a-tool could demote at the final task). Conservative tiebreaker restored.
- **F2 (known limitation, documented):** enforcement fires only on the structurally-last task; when the CLI is built earlier and the last task is tests/docs (not applicable), the gate observes rather than enforces — safe direction (under-enforce, never false-fail). A fuller "deliverable complete" signal is a follow-up / feature 3. Documented in contract + arch.
- **F3 (known limitation):** a run aborting at `max_failures` before the final task is never acceptance-checked (the run already failed). Acceptable.

Both passes clear after F1/F4 + the doc/contract delta → ready for ship.

<!-- NOTE (timing fix, 2026-06-06): commit `1929ce0` (three-signal demotion) + `a24ef16`
     (arch design) landed AFTER the Pass-2 stamp above. The timing fix is purely additive
     (a new `should_run_now` position gate that narrows the demoting surface) and the full
     suite is green at 1282/40 — Pass-1 re-checked it (see the timing-fix section above).
     The orchestrator should confirm whether Pass-2 (code-review) needs a re-run over the
     timing-fix diff before ship; the Pass-1 re-check is approve. -->
