# Execution state

Single source of truth for the currently active task. Overwritten as the task progresses; archived to `.ai-pm/state/archive/<topic>-<YYYY-MM-DD>.md` on completion.

PM reads this when curious about progress; PM never edits it. Agents read it as their first step and update it as their last step.

---

## Task

Feature 3 of the backend redesign: `feat/acceptance-self-fix-loop` — turn the
acceptance gate's terminal `done → failed` demotion into a **bounded, trust-gated
self-fix loop**. On a failing final-task run-smoke (applicable × `should_run_now` ×
fail) at `optimist`/`yolo`, re-feed the run-smoke output to `code_with_retry`,
rebuild, re-verify — up to a configurable budget (default 3) — before finally
`failed`. At `skeptic`: no auto-fix, `failed` immediately (unchanged). The
consistency lever toward a stable `notes_cli` 3/3.

Plan: `docs/features/acceptance-self-fix-loop_plan.md`.
Arch: `.ai-pm/arch/acceptance-self-fix-loop_arch.md`.
Advocate gate: `.ai-pm/reviews/acceptance-self-fix-loop_advocate.md` (clean).
Decision authority: interactive (project default).

## Status

COMPLETE — shipping. Coding + both review passes + doc/contract handoff + live
probe all done. Pipeline green (pytest 1298 passed / 40 skipped; ruff check +
format clean; mypy clean except the known pre-existing `tools/files.py:8`
unused-ignore, out of scope).
- Pass 1 (pm-plan-checker): approve.
- Pass 2 (code-review on Sonnet + seam-completeness on session): no blocking
  findings. F1/F6 (doc/comment accuracy) fixed in 8263aed; F2/F4/F5 accepted
  with context → `.ai-pm/backlog.md`. Stamp written.
- Doc/contract handoff: pm-architect updated user-journeys/architecture
  (SC8)/threat-model/plan.md; orchestrator updated the run-plan contract.
- Step 5.5 live probe: ran `notes_cli` through qwen14b — no regression (clean
  run, max_failures stop, partial progress kept), derive correct. Self-fix
  could NOT be exercised live: every run-smoke returned `skipped
  (pkg-unresolvable)` — the pre-existing flat-layout reach gap blocks the
  acceptance verdict upstream, so there is no demotion for self-fix to act on.
  Logic stays proven by the unit suite (incl. the production run_plan
  end-to-end recovery test). Flat-layout gap → backlog.
- PM ship decision: C (ship now). Merge stays with the PM on GitHub.

## Done

- Features 1 (PR #168), 2 (PR #169), 4 (PR #170) merged. Acceptance gate ENFORCES
  (demotes `done → failed`) when intent × position × state agree.
- **Planning (this task):**
  - PM decisions captured: (1) ON by default, (2) trust-gated (skeptic = no autofix;
    optimist/yolo = autofix), (3) budget = configurable, default 3.
  - Focused `pm-architect` arch note: Q1 loop home = `plan_runner._run_task` (verify
    stays a pure reporter); Q2 failure signal = inline on `TaskOutcome` (not persisted);
    trust gate = `policy.auto_confirm`; one outer anti-loop guard (identical run-smoke
    output 2× → stop); combined bound ~9 build passes accepted; threat-model flagged.
  - Plan: 7 scenarios + 2 failure paths + KD1–KD10 + test plan + Docs-to-update + DoD.
  - Product-readiness gate clean (all five per-feature foundational questions answered).
- **Coding (this task — pm-coder):**
  - Config knobs landed in `code_scalpel/config.py` `AgentConfig`: `acceptance_self_fix`
    (=True) + `acceptance_self_fix_max_attempts` (=3) (KD4, no magic numbers).
  - `TaskOutcome` gained `acceptance_output: str | None = None` (KD2) — set inline by
    `verify_task`/`_verify_acceptance` on any failing applicable run-smoke, preserved by
    `_demote`'s `dataclasses.replace`, NOT persisted to STATE.json. `_run_smoke` now
    returns the raw `ToolResult.output` as a 6th tuple element.
  - Self-fix orchestration on `PlanRunner`: `_run_task` extracted into `_build_task`
    (per-attempt HEAD re-snapshot + skills + one code_with_retry pass), `_acceptance_demoted`
    (the acceptance-vs-checks-1-3 discriminator), `_self_fix_acceptance` (the bounded loop:
    trust gate via `policy.auto_confirm` KD3, budget KD4, identical-output break KD5,
    failure-path-8 raise guard), `_self_fix_prompt` (KD9 — adapter command + run-smoke
    output only; no python/-m/notes_cli literal). `_run_task` kept under 50 lines (KD10).
  - Tests: new `tests/test_acceptance_self_fix.py` — all plan-named tests (recovery, budget,
    skeptic, off-switch, identical-break, early-task, library, signal-reaches-builder, two
    failure paths, HEAD re-snapshot, recovered-commit, config-defaults, language-agnostic) +
    a production `run_plan` end-to-end recovery test (test-wiring-parity). 15 tests, all green.
  - NO existing test needed modification: `test_acceptance_enforcement.py` (verify_task-direct)
    unaffected; the run_plan-level `test_run_loop_demotes_only_the_final_applicable_task` still
    passes as-is (its retry build produces a non-applying patch so self-fix stops at the first
    re-verify — no behavior change to assert).

## Remaining

- Review loop: Pass 1 `pm-plan-checker`, Pass 2 `code-review`.
- Post-coding doc handoff (`pm-architect`): user-journeys.md (Journey 5 step 3),
  architecture.md (new decision + §Task outcome status + new SCn + File layout),
  threat-model.md (T05/T06/T10 + SCn + Last reviewed bump), plan.md (✓ feature 3).
  Orchestrator: `.ai-pm/contracts/run-plan.md` (Must-work add, remove Out-of-scope
  deferral, update Acceptance-checks). Then product-map regen + contract Built/changed-by.
- Verify (Step 5.5): live `notes_cli` probe — self-fix recovers a failing final-task
  build → stable 3/3 task_solved, BEFORE ship.
- Ship: pr-prep + PR (merge authorized by PM).
- Later: feature 5 (node-cli-adapter).

## Touched files

- `code_scalpel/config.py` — two new `AgentConfig` fields (KD4).
- `code_scalpel/agent.py` — `TaskOutcome.acceptance_output` field (KD2).
- `code_scalpel/plan_verify.py` — `_run_smoke` returns raw output (6th tuple element);
  `_verify_acceptance` attaches it to the outcome on a failing applicable verdict.
- `code_scalpel/plan_runner.py` — `_run_task` refactor + `_build_task`,
  `_acceptance_demoted`, `_self_fix_acceptance`, `_self_fix_prompt`; `_last_step_result`
  on `__init__`.
- `tests/test_acceptance_self_fix.py` — NEW, 15 tests.
- (NOT touched, per KD2: `state.py` — no new state field.)

## Next step

review — Pass 1 `pm-plan-checker` (plan compliance), Pass 2 `code-review`
(technical quality). Then post-coding doc handoff (pm-architect) + contract update
(orchestrator), then Step 5.5 live `notes_cli` probe, then ship.

## Validation

Per plan Test plan + DoD. Pipeline: pytest / ruff check / ruff format --check /
mypy code_scalpel/. Feature acceptance: live `notes_cli` self-fix probe → stable 3/3
before ship.

## Notes

Mature codebase (v0.14 open). Interactive mode. The three product forks were resolved
by the PM at planning. verify_task stays a pure reporter (KD1) → feature-4's
verify_task-direct tests in test_acceptance_enforcement.py are unaffected; only
run_plan-level tests driving a failing final-task at optimist/yolo may need a justified
trust/mocks adjustment.

---

## How to use this file

- **Agent step 1** — read this file before doing anything else. If it says "done", do not start work without explicit PM instruction to start a new task.
- **Agent step last** — overwrite this file with the new state before stopping.
- **Session restart** — re-read this file. It should be enough to continue without scrolling chat history.
- **Task complete** — copy this file to `.ai-pm/state/archive/<topic>-<YYYY-MM-DD>.md` and reset this one to a new task or to "Status: idle".
