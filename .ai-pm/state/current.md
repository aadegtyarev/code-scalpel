# Execution state

Single source of truth for the currently active task. Overwritten as the task progresses; archived to `.ai-pm/state/archive/<topic>-<YYYY-MM-DD>.md` on completion.

PM reads this when curious about progress; PM never edits it. Agents read it as their first step and update it as their last step.

---

## Task

`feat/flat-layout-run-smoke` — close the two gaps that keep the acceptance gate +
self-fix loop inert on the canonical scenario: (A) make run-smoke resolve and run
flat-layout python CLI deliverables (root package / root script / `[project.scripts]`),
and (B) enforce the runnable CLI at the **last applicable task** (not the last plan task),
so a failing CLI run-smoke demotes and self-fix engages at optimist/yolo. PM-approved
scope A+B.

Plan: `docs/features/flat-layout-run-smoke_plan.md`.
Arch: `.ai-pm/arch/flat-layout-run-smoke_arch.md` (Q1 typed RunTarget descriptor;
Q2 `_last_applicable_index`).
Decision authority: interactive (project default).

## Status

CODING (handoff pending batch completion). Plan approved by PM ("норм поехал").
Arch note done. Product-readiness gate: EXEMPT (scenario subjects are non-human —
system/deliverable/gate; backend correctness fix to make existing promised behavior
work). Reuses the existing `run-plan` contract — no new contract.

## Done

- Step-5.5 finding (prior feature): self-fix inert on canonical scenario.
- Baseline probe batch on `main` (c3a1097), N=5: mechanical scores 7/8, 7/8, 4/8, 4/8
  (run 5 finishing) — all runs stop early (max_failures); ~69% deliverable completeness.
  Recorded as the before-number for the post-feature comparison.
- Arch note: Q1 `resolve_pkg → RunTarget(kind, target)` with deterministic precedence
  (declared outranks discovered; ambiguity/absence → raise); Q2 enforce at
  `_last_applicable_index` via the existing pure `acceptance_applicable` predicate —
  verify_task + self-fix helpers UNCHANGED.
- Plan written + PM-approved.

## Remaining

- Coder: implement Gap A (resolver descriptor + adapter argv shape + config candidate
  list) + Gap B (`_last_applicable_index` position) + the full test plan. Never touch
  existing tests.
- Post-coding doc handoff (pm-architect): architecture.md (Task outcome status / State
  model / decision record / resolve_pkg descriptor), threat-model.md (T05/T06/T10 reach
  + Last reviewed), plan.md (§31). Orchestrator: run-plan contract (position wording,
  clear both Out-of-scope reach-gap lines, Must-work + Acceptance-checks).
- Review loop: Pass 1 pm-plan-checker, Pass 2 code-review.
- Step 5.5: re-run notes_cli probe batch (N=5), compare to baseline (the measurable win).
- Ship: pr-prep + PR.

## Touched files

(to be filled by coder) — expected: code_scalpel/skills/python_pkg.py,
code_scalpel/skills/python_cli_adapter.py, code_scalpel/config.py,
code_scalpel/plan_runner.py, code_scalpel/plan_verify.py (position source),
tests/ (new resolution + adapter + enforcement-position tests).

## Next step

Wait for baseline batch to finish (do not let coder edit code mid-batch — would
contaminate the baseline), clean up baseline run dirs, then spawn pm-coder.

## Validation

Per plan Test plan + DoD. Pipeline: pytest / ruff check / ruff format --check /
mypy code_scalpel/. Feature verification (Step 5.5): notes_cli probe batch before/after
(baseline 7/8, 7/8, 4/8, 4/8).

## Notes

Mature codebase (v0.14 open). Interactive mode. Two design decisions are settled in the
arch note (minimal blast radius — verify_task + self-fix helpers untouched; only WHICH
task triggers enforcement changes, and WHAT shape resolve_pkg returns).

---

## How to use this file

- **Agent step 1** — read this file before doing anything else. If it says "done", do not start work without explicit PM instruction to start a new task.
- **Agent step last** — overwrite this file with the new state before stopping.
- **Session restart** — re-read this file. It should be enough to continue without scrolling chat history.
- **Task complete** — copy this file to `.ai-pm/state/archive/<topic>-<YYYY-MM-DD>.md` and reset this one to a new task or to "Status: idle".
