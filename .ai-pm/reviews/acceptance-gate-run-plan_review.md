# acceptance-gate-run-plan — Pass-1 plan compliance

Selection provenance: plan `Source:` cites `backend redesign migration step 2` + `.ai-pm/arch/backend-redesign_arch.md` — sourced. Decision authority: `autonomous` (per-feature override, recorded in plan line 3). `## Resolutions` #1 is an `escalated` PM decision (the "plumbing only" re-scope) — not an `auto` entry, so no citation-check applies; advocate verdict is `clean`.

> **Re-review 2026-06-06 (Pass-1 re-run #2).** The prior verdict was `request-changes` on a single blocker: the plan's "Docs to update" were not on-branch. Since then the feature was **re-scoped by PM to PLUMBING ONLY** (verification #4 is observational — records + surfaces the run-smoke verdict but NEVER demotes; enforcement deferred to feature 4), recorded in `## Resolutions` #1 and the plan's "SCOPE — plumbing only" note. Code fix `c01052e`; docs handoff `b2a1ad5`. This re-run verifies the re-scoped plan against the implementation and the now-landed docs. **All five doc updates are on-branch and describe the observational (non-enforcing) behavior; the code is genuinely plumbing-only. → approve.**

## Plan compliance

Scenarios (re-scoped — observational, never demotes):
- ✓ S1 keep `done` when run-smoke succeeds, verdict recorded `passed` — `plan_verify._verify_acceptance` returns `outcome` unchanged; tests `tests/test_acceptance_gate.py::test_acceptance_gate_keeps_done_when_runsmoke_succeeds` + `test_acceptance_records_passed_when_runsmoke_succeeds`.
- ✓ S2 non-zero exit → verdict recorded `failed` + surfaced, **task NOT demoted** (re-scoped — plumbing only) — `_verify_acceptance` always `return outcome`; no `status="failed"` construction in `_verify_acceptance`/`_run_smoke` (grep-confirmed: the only `status="failed"` is `_demote`, line 53, called solely from `verify_task` checks 1-2). Test `test_acceptance_records_failed_but_does_NOT_demote_when_runsmoke_fails` asserts `out.status == "done"`, `out.task is _TASK`, `step_result is`, `verdict == "failed"`.
- ✓ S3 logged no-op when no acceptance adapter — `adapter is None` branch records `noop`, status unchanged; test `test_acceptance_gate_noop_when_no_acceptance_adapter` (asserts no shell dispatched + verdict `noop`).
- ✓ S4 resolved through registry, never hardcoded — `acceptance_adapter(agent._cwd)` → `SkillRegistry.acceptance_adapter`; test `test_acceptance_adapter_resolution_drives_production_registry`.
- ✓ S5 surfaced to user via existing card seam — `_emit_acceptance_card` rides `on_tool_executed`; test `test_acceptance_card_surfaced`.
- ✓ S6 persisted — `_record_acceptance` writes the three `AgentState` fields; tests `test_state_persists_runsmoke_verdict_and_reason` + `test_runsmoke_verdict_resumes_from_state`.
- ✓ S7 timeout → recorded `failed`, timeout from config (no magic number), no demotion — tests `test_acceptance_runsmoke_timeout_fails` (asserts `out.status == "done"`, reason `timeout`) + `test_acceptance_runsmoke_uses_config_timeout` (asserts `seen == [_SHELL_TIMEOUT]`, config-sourced).
- ✓ S8 `resolve_pkg` raises → recorded `failed`, reason `pkg-unresolvable`, NO new status, no demotion — `_run_smoke` catches `ValueError`; test `test_acceptance_pkg_unresolvable_records_reason` (asserts `done`, reason + no shell dispatched).
- ✓ S9 bwrap unavailable → degrades via shared `execute()` path, no special-casing — run-smoke goes through `execute(..., sandbox=…)`, inheriting policy/bwrap degradation; correctly NOT re-tested here (inherited from the shared primitive per plan; degradation is owned/tested at the `execute()`/`policy.py` boundary). Acceptable.

Re-scope-specific guards (the load-bearing no-regression evidence for the PM "plumbing only" decision):
- ✓ `test_acceptance_library_project_not_demoted` — BOTH layouts: a src-layout library (no `__main__.py`, run-smoke exits non-zero) and a flat-layout library (`resolve_pkg` raises → `pkg-unresolvable`) each record `failed` yet stay `done`. This is the exact `done→failed` regression the plumbing-only scope prevents.
- ✓ `test_acceptance_does_not_inherit_exit_4_5_leniency` — exit 4 AND 5 both record `failed` (not the test-command leniency) **and** the task stays `done` (no demotion).
- ✓ `test_noop_does_not_clobber_prior_verdict_or_persist` — a later `noop` does not overwrite an earlier `passed`/`failed` and triggers no redundant `_persist_state` write (`persist_calls == 0`).
- ✓ `test_acceptance_expected_observable_checked_when_nonempty` — non-empty `expected` absent from output → recorded `failed` (`expected-missing`), present → `passed`; floor (`expected == ""`) stays exit-0-only.

Named Test-plan tests — all present and test what they claim:
- ✓ test-wiring-parity: `test_acceptance_adapter_resolution_drives_production_registry` drives the MODULE-LEVEL production `acceptance_adapter` (not a hand-built registry), asserts root-bound `PythonCliAdapter` via `provides_acceptance`, `default_runnable_skill` unchanged = `PythonSkill`, and `None` for a no-adapter root. Production registration path = the path the run-loop takes (`plan_verify` imports `from code_scalpel.skills import acceptance_adapter`). Parity satisfied.
- ✓ stack-spec tests cite source URLs in comments and verify the rule: `test_runsmoke_uses_argv_no_shell` cites the asyncio-subprocess security-considerations URL and asserts argv round-trips with no shell metacharacters; `test_runsmoke_cwd_pinned_to_root` cites SC2 and asserts cwd == project root. Verified against the rule, not a self-consistent mapping.
- ✓ `test_plan_modified_still_stops_with_gate_active` (interaction) — gate active on python-cli root, mid-run `TASKS.md` edit still yields `stopped_reason == "plan_modified"`.
- ✓ AgentState forward-compat — `test_state_persists_runsmoke_verdict_and_reason` loads a legacy `STATE.json` without the new keys → defaults `unknown`/`None`.
- ✓ bind/capability units: `test_bind_default_returns_self`, `test_bind_python_cli_returns_root_bound`, `test_provides_acceptance_flag` (PythonCliAdapter True; Python/Go/JsTs/Docker/Postgres/Sqlite all False).

Contracts:
- ✓ `Skill.provides_acceptance: bool = False` (base.py), `True` on PythonCliAdapter.
- ✓ `Skill.bind(root)` default `return self`; PythonCliAdapter returns `PythonCliAdapter(root=root)`.
- ✓ `SkillRegistry.acceptance_adapter` — UNFILTERED scan, detects on rootless singleton then returns `.bind(root)`, `None` when none detect.
- ✓ verification #4 placement — `verify_task` runs it last, after a still-`done` outcome; `_verify_acceptance` returns the outcome unchanged in EVERY branch (re-scoped observational); exit-0-or-fail in the recorded verdict (no exit-4/5 leniency).
- ✓ AgentState fields default-valued, atomic persist via existing `save()`/`_persist_state` under `suppress`; persist skipped on the no-op/no-change path.

Interaction scenarios — all four covered:
- ✓ plan_modified with gate active (`test_plan_modified_still_stops_with_gate_active`).
- ✓ registry resolution independent of `default_runnable` (`test_acceptance_adapter_resolution_drives_production_registry`).
- ✓ resume-from-state (`test_runsmoke_verdict_resumes_from_state`).
- ✓ skeptic-trust yolo execution (`test_runsmoke_executed_via_yolo_plan_owned_path` — runs at yolo on a skeptic agent without a confirm handler).

Strangle is genuinely behavior-preserving:
- ✓ Existing `run_plan` tests in `tests/test_agent.py` NOT edited — additive only; full suite green (1249 passed, 40 skipped).
- ✓ `_classify_outcome` unchanged — still defined at `agent.py:694`; the one diff line is the call moving into the extracted module (the `def` is untouched); status taxonomy `done|failed|skipped` unchanged.
- ✓ `Task.acceptance` NOT consumed — the only diff mention is an arch-note comment stating it stays unused (feature 4 input).
- ✓ run_plan is a thin delegator into `PlanRunner`.

Out of scope NOT touched:
- ✓ No self-fix route-back; no task-declared/narrow-pass acceptance; no NodeCliAdapter; no new outcome status; no CI automation of the outcome probe.
- ✓ **Enforcement / demotion** — explicitly NOT implemented (the re-scope); `_verify_acceptance` never demotes.
- (`plan_loading.py` / `plan_post_checks.py` / `plan_verify.py` split — plan-permitted to honor the ≤300-line minimum; conformant, not scope creep.)

Categorical coverage: the chosen categorical surface ("how acceptance is specified") ships A (floor) only; siblings B/C and other-language adapters are each listed under Out of scope with a reason. Covered.

## Definition of Done
- [x] All plan scenarios implemented and tested
- [x] Interaction scenarios have concurrent-state tests
- [x] Stack expectations respected; stack-spec tests pass (argv-no-shell, cwd-pinned-root both cite source + verify the rule)
- [x] Product Contract honored; Acceptance checks pass; no silent behavior change — `.ai-pm/contracts/run-plan.md` updated (working tree): `## Must work` adds the run-smoke recording/surfacing; `## Must not break` states it is **recorded, not enforced** and **must not break any existing `/go` flow** (incl. python libraries); Acceptance checks reference the two no-demote tests; Out of scope defers enforcement to feature 4. The contract matches the re-scoped observational behavior — no silent behavior change (the user-visible change IS "a per-task run-smoke card", which the contract + Journey 5 now describe).
- [x] Pipeline green — pytest 1249 passed / 40 skipped, ruff check + format clean. (mypy: one `unused-ignore` at `code_scalpel/tools/files.py:8` — confirmed NOT in this branch's diff, byte-identical to `main`; an environment/stub artifact, clean on a cacheless run modulo this pre-existing flicker, not attributable to this feature. See Notes 1.)
- [x] State file updated (`.ai-pm/state/current.md`)
- [x] Product Impact Report present (when contract touched) — the contract change is the recorded-not-enforced re-scope; the product impact (observational card, no `done→failed` regression) is documented in `## Resolutions` #1, the contract `## Must not break`, and Journey 5. No separate enforcement-driven behavior change requiring a standalone PIR beyond this.
- [x] Docs updates landed — all five on-branch and describing OBSERVATIONAL behavior: `docs/architecture.md` (new "Acceptance run-smoke (verification #4) — observational (v0.14)" decision + `plan_verify.py`/`plan_runner.py` file-layout + task-outcome verdict + state-model notes, all "records/surfaces but never demotes"), `docs/user-journeys.md` (Journey 5 new step + invariant: run-check is **informational in this version**, does NOT decide done/failed), `docs/threat-model.md` (new T11 + trust-boundary row + Last reviewed 2026-06-06; security-bearing project, shell-exec surface), `docs/plan.md` (v0.14 ✓ mark, plumbing-only with enforcement deferred), `.ai-pm/contracts/run-plan.md`.
- [x] Expected artifacts exist (plan, this review, run-plan contract for the user-facing feature)
- [x] Product-readiness gate resolved — advocate artifact `clean` (`.ai-pm/reviews/acceptance-gate-run-plan_advocate.md`)
- [n/a] Validation gate — software-kind project
- [x] Failure-inventory negative-space tests present — S7/S8 (timeout, pkg-unresolvable) each have a failure-path test that also asserts no-demotion

**DoD: pass**

## Blocking

None. The prior blocker (docs-to-update not on-branch) is resolved: all five doc updates landed on-branch (commit `b2a1ad5` + the working-tree contract) and correctly describe the re-scoped observational behavior, not a "done now requires run-smoke" claim. The code is verified plumbing-only — `_verify_acceptance`/`_run_smoke` carry no `status="failed"` construction and never call `_demote`; the only demotions are checks 1-2 in `verify_task`.

## Notes (product)
1. mypy reports one `unused-ignore` at `code_scalpel/tools/files.py:8` — a file untouched by this branch (byte-identical on `main`; confirmed absent from the diff). It surfaces from the installed `pathspec` stub set in this environment, not from the feature. Surfaced only so the orchestrator knows the env's mypy line isn't 100% clean and can decide whether to clean it up opportunistically; not attributable to this feature and not a plan-compliance block. **Why it matters:** a non-green pipeline line, even pre-existing, can mask a real regression later; worth a one-line cleanup in a separate fixup, not in this branch.
2. The plan's "Docs to update" bullets (lines 104–105) still carry the pre-re-scope framing ("a `done` task now requires run-smoke to pass" / "flips to `failed`"). The *landed* docs correctly describe the observational behavior recorded in `## Resolutions` #1, so there is no doc/behavior mismatch — but the plan's own Docs-to-update prose was not refreshed to the plumbing-only wording. **Why it matters:** purely a stale-plan-text observation for the PM; the shipped artifacts (docs, contract, code) are all consistent with the re-scoped intent. No action required for this PR.

## Verdict
approve

<!-- The trail below is the ONE review section the orchestrator owns, not pm-plan-checker.
     See the "Edit-ownership rule" in `workflow/enforcement.md` — the Pass-2 code-review
     trail is the single carve-out to "orchestrator does not edit content artefacts". -->
## Code review findings
Pass-2 technical review (code-review skill, high effort: 7 finder angles → verify). Strangle audited separately (angle B): **behavior-preserving** — every original run_plan behavior survives with identical semantics/ordering (re-hash/plan_modified, streak counting + thresholds, auto-commit + HEAD no-op "keep done", pre-loop passes, compaction, callback timing). One inert landmine noted (F7).

### Blocking — escalated to PM (genuine product-scope fork)

1. **The acceptance gate misfires on python LIBRARY projects → net-new `done→failed` regression.** `PythonCliAdapter.detect` delegates to `PythonSkill.detect`, which fires for ANY python project (pyproject/requirements/setup), not just CLIs. With `provides_acceptance=True`, `acceptance_adapter(root)` now resolves the CLI run-smoke gate for libraries too. Reproduced live: a src-layout library (`src/mylib/__init__.py`, no `__main__.py`) → `resolve_pkg` returns `mylib` → `python -m mylib --help` fails → task demoted; a flat-layout library → `resolve_pkg` raises → `pkg-unresolvable` → demoted. `main` has no acceptance gate, so library `/go` tasks that were `done` now fail. The tension: the gate's target bug (the notes_cli coin-flip) IS "no `__main__.py`" — indistinguishable from a legitimate library without a CLI-intent signal, which is feature 4 (task-declared) territory. **Resolution direction is a product decision — escalated to PM (see `## Resolutions`).** Fix routed to coder once the PM picks the direction.

### Blocking — fix in the same pass (routed to coder)

2. **`_run_smoke` discards the `_expected` observable; only `result.ok` is checked.** Correct for the current floor (`expected == ""` ⇒ exit-0-only), but a baked-in false-green: the moment any adapter returns a non-empty expected string, a deliverable that exits 0 while printing nothing passes acceptance. **Fix:** when `expected` is non-empty, also require it to appear in the run-smoke output; keep exit-0-only when empty. Add a test.

3. **`_record_acceptance` persists on every task (incl. the no-op branch) AND a `noop` clobbers a prior real verdict.** A full atomic STATE.json write per task on every non-acceptance project (the common case), and a later `noop` overwrites an earlier `passed`/`failed`. **Fix:** skip the persist on the no-op branch (or only persist on change); never let `noop` overwrite a meaningful verdict.

### Non-blocking cleanups (bundle in)

4. **`_failure_reason` reverse-engineers the exit code by string-grepping `ToolResult.output`** (`"timeout" in out`; line starting `exit code:`). Fragile (the broad `timeout` substring false-matches output that merely contains the word; refusal/`error:` outputs degrade to the generic `run-smoke failed`, hiding e.g. a missing-bwrap config from feature 3's self-fix). The pass/fail decision itself is `result.ok` (correct) — only the reason string is affected. **Fix:** prefer a structured exit code if `ToolResult` exposes one; else tighten the parse (anchor the timeout match; map refusal/error explicitly).
5. **Redundant `outcome.status != "done"` re-guard in `_verify_acceptance`** — dead today (`_verify_head_advanced` never demotes); collapse the guards or document that `_verify_head_advanced` is demotion-incapable by contract, so a future demotion isn't silently swallowed.
6. **`spec is None` treated as a silent PASS** (`provides_acceptance=True` but no spec is a self-contradictory state) — record it as a visible `noop`/`unknown` with a reason, not an unqualified pass.
7. **`plan_loading.py` annotation no-change branch re-parses markdown**, dropping the typed `Task` fields (goal/files/acceptance/skills/test_command) when the plan came from TASKS.json. Inert today (the loop is `task.body`-driven) but a latent landmine. **Fix:** return the existing typed `tasks` tuple unchanged on the no-change path instead of re-parsing.
8. Three literal copies of `TaskOutcome(..., status="failed")` — extract a `_demote(outcome)` helper.

**Orchestrator decision:** finding 1 escalated to PM (product fork). Findings 2–3 block ship; 4–8 bundled into the same fix pass. All routed to `pm-coder` after the PM resolves #1.

## Resolutions

1. **Library-misfire fork (finding 1) — RESOLVED by PM: "plumbing only" (escalated).** The PM chose to ship the mechanism (`provides_acceptance` / `bind` / `acceptance_adapter` / run-smoke execution / state persistence / surfaced card) but **NOT** turn on hard enforcement now: verification #4 becomes **observational** — it runs the deliverable's run-smoke, records the verdict, and surfaces the card, but **never demotes a task to `failed`**. The hard gate (demote-on-failure) is deferred to feature 4 (`feat/acceptance-spec-in-tasks`), which supplies the CLI-vs-library signal that lets the gate fire only on CLI deliverables. Consequence: no `done→failed` regression for any project type (libraries included); `notes_cli` 3/3 `task_solved` moves to feature 4's acceptance criterion. Plan re-scoped accordingly (`docs/features/acceptance-gate-run-plan_plan.md`). Marker: `escalated` → PM decision recorded here.

## Code review: 2026-06-06 — passed

All Pass-2 findings closed in fix commit `c01052e` (verified on the branch):
- **Finding 1 (escalated → PM "plumbing only")**: verification #4 is now observational — `_verify_acceptance`/`_run_smoke` contain NO `status="failed"` construction; the only demotions (`_demote`, `plan_verify.py:53`) are checks 1–2 in `verify_task`. The library misfire is gone (`test_acceptance_library_project_not_demoted`, both layouts). Enforcement deferred to feature 4.
- **Finding 2 (expected observable)**: non-empty `expected` now required in output for `passed` (`test_acceptance_expected_observable_checked_when_nonempty`); floor stays exit-0-only.
- **Finding 3 (persist-on-noop / clobber)**: no persist on noop/no-change; noop never clobbers a real verdict (`test_noop_does_not_clobber_prior_verdict_or_persist`).
- **Findings 4–8 (cleanups)**: `_failure_reason` tightened (anchored timeout, distinct `refused`); redundant guard documented; `spec is None` → visible noop with reason; `plan_loading` no-change branch returns the typed tasks unchanged; `_demote` helper extracted.

Strangle confirmed behavior-preserving (angle B). Pipeline green: pytest 1249 passed / 40 skipped; ruff check + format clean; mypy clean on a cacheless run (the `tools/files.py:8` flicker is a cache/stub artifact, not in this diff). Both passes clear → ready for ship.
