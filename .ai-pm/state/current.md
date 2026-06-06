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

PLANNING COMPLETE — handed off to pm-coder. Branch `feat/acceptance-self-fix-loop`
cut from main. Product-readiness gate clean. PM approved the plan (on-by-default,
trust-gated, budget=3 configurable).

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

## Remaining

- **Coding (pm-coder):** config knobs (`acceptance_self_fix`=True,
  `acceptance_self_fix_max_attempts`=3); inline run-smoke output on `TaskOutcome`
  (default None, preserved by `_demote`); self-fix orchestration helper on the runner
  wired into `_run_task` (trust gate + budget + identical-output break); zero language
  strings in the loop. Tests written with the code (new `tests/test_acceptance_self_fix.py`).
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

(to be filled by coder; planned surface — code_scalpel/config.py, plan_runner.py,
plan_verify.py [TaskOutcome field + return the run-smoke output], agent.py [if
code_with_retry needs a signal-passing seam], state.py [no new field per KD2],
tests/test_acceptance_self_fix.py [new])

## Next step

pm-coder implements per `docs/features/acceptance-self-fix-loop_plan.md` honoring
the arch note's "what the plan / coder must honor" list (KD1–KD10).

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
