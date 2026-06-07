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

PASS-2 CODE-REVIEW FIXES DONE — pipeline green. All five findings (CR1–CR5)
addressed with tests for the four behavioral fixes (CR1/CR2/CR3/CR5).
Awaiting re-verify + stamp by code-review.

CODING DONE — pipeline green. Plan approved by PM ("норм поехал"). Arch note done.
Product-readiness gate: EXEMPT (scenario subjects are non-human — system/deliverable/
gate; backend correctness fix to make existing promised behavior work). Reuses the
existing `run-plan` contract — no new contract.

Two atomic commits on `feat/flat-layout-run-smoke` (not pushed):
- Gap A: flat-layout run-smoke resolution via typed RunTarget.
- Gap B: enforce at last-applicable task, not last task.

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
- CODER: Gap A — `resolve_pkg → RunTarget(kind,target)` + precedence ladder + adapter
  argv-from-kind + config candidate list (`run_smoke_script_candidates`). Gap B —
  `_last_applicable_index(tasks, adapter)` drives `should_run_now`; `_last_not_done_index`
  kept as fallback. verify_task + all feature-3 self-fix helpers byte-for-byte unchanged.
  +34 tests (tests/test_python_pkg.py, tests/test_flat_layout_run_smoke.py); no existing
  test modified. Pipeline green (pytest 1332 passed / 40 skipped; ruff check + format
  clean; mypy clean except the pre-existing files.py:8 unused-ignore on main).

## Remaining

- Pass-2 re-verify + stamp by code-review (the `## Code review` trail in the review file).
- Post-coding doc handoff (pm-architect): architecture.md (Task outcome status / State
  model / decision record / resolve_pkg descriptor), threat-model.md (T05/T06/T10 reach
  + Last reviewed), plan.md (§31). Orchestrator: run-plan contract (position wording,
  clear both Out-of-scope reach-gap lines, Must-work + Acceptance-checks).
- Review loop: Pass 1 pm-plan-checker, Pass 2 code-review.
- Step 5.5: re-run notes_cli probe batch (N=5), compare to baseline (the measurable win).
- Ship: pr-prep + PR.

## Touched files

- code_scalpel/config.py — `run_smoke_script_candidates` field + CR3 simple-filename validator.
- code_scalpel/skills/python_pkg.py — `RunTarget` descriptor + precedence ladder;
  CR2 reserved-dir exclusion; CR3 traversal-skip; CR4 docstring; CR5 symmetric src ambiguity.
- code_scalpel/skills/python_cli_adapter.py — argv-from-kind; CR1 `bind(root, script_candidates)`
  + corrected comment.
- code_scalpel/skills/base.py — CR1 `bind` gains optional `script_candidates`.
- code_scalpel/skills/registry.py + skills/__init__.py — CR1 `acceptance_adapter(root, candidates)`.
- code_scalpel/plan_verify.py — CR1 re-bind resolved adapter with live config candidates.
- code_scalpel/plan_runner.py — `_last_applicable_index` + `should_run_now` source.
- tests/test_python_pkg.py, tests/test_flat_layout_run_smoke.py, tests/test_config.py
  — CR1/CR2/CR3/CR5 tests added (no existing test modified).

## Next step

Review loop: Pass 1 pm-plan-checker, Pass 2 code-review. Then post-coding doc handoff
(pm-architect for docs/, orchestrator for the run-plan contract). Then Step 5.5
notes_cli probe batch (N=5) vs baseline, then ship.

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
