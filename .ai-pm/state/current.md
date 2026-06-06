# Execution state

Single source of truth for the currently active task. Overwritten as the task progresses; archived to `.ai-pm/state/archive/<topic>-<YYYY-MM-DD>.md` on completion.

PM reads this when curious about progress; PM never edits it. Agents read it as their first step and update it as their last step.

---

## Task

Implement feature 2 of the backend redesign: `feat/acceptance-gate-run-plan` — add a 4th mandatory machine check to `run_plan`'s Definition-of-Done that runs the deliverable as a user would (`python -m <pkg>`) via a registry-resolved ProjectAdapter, so a task can no longer be `done` on proxies. Strangle `run_plan` into its own module first (behavior-preserving), then add the gate. Plan: `docs/features/acceptance-gate-run-plan_plan.md`. Arch: `.ai-pm/arch/acceptance-gate-run-plan_arch.md`. Decision authority: autonomous (per-feature, PM "на автомате").

## Status

planning complete — ready for coder handoff

## Done

- Feature 1 (`feat/project-adapter-abstraction`) merged: PR #168 (squash `0f79f95`). ProjectAdapter contract + PythonCliAdapter + registry `hidden` trait. Archived prior state.
- Repo housekeeping: probe-run corpus committed; `.ai-pm/tooling/` + probe `.workdir/` gitignored.
- **This task (planning):**
  - Read context: arch note (parent), run-plan contract, architecture.md (taxonomy/release-gate/invariants), stack-notes (subprocess/python-m/bwrap/asyncio), user-journeys Journey 5, security-surfaces, decision-authority.
  - Mapped the run-loop AS-IS: `run_plan` agent.py:1219–1695 (477 lines), verification block 1459–1526 (3 checks), `_classify_outcome` 694–719, `execute(..., trust="yolo")` shell path, `PythonCliAdapter(root=...)` resolution, `AgentState`/STATE.json, `on_task_end`/`on_tool_executed` TUI seam. `Task.acceptance` exists but unused (feature 4 input).
  - Ran focused `pm-architect` → `.ai-pm/arch/acceptance-gate-run-plan_arch.md` (design confirmed with refinements: no exit-4/5 leniency; `pkg-unresolvable`→failed reason-string, no new status; `PlanRunner(self)` strangle; yolo provenance flagged forward to feature 4).
  - Wrote plan `docs/features/acceptance-gate-run-plan_plan.md` (9 scenarios incl. 3 failure paths; contracts; stack expectations; interaction scenarios; full test plan; docs-to-update; out-of-scope).
  - Product-readiness gate (`pm-product-advocate`): **clean** — all 5 foundational questions answered. `.ai-pm/reviews/acceptance-gate-run-plan_advocate.md`.

## Remaining

- Coder: implement on `feat/acceptance-gate-run-plan` — commit 1 behavior-preserving `run_plan`→`plan_runner.py` strangle (existing tests green), commit 2 the acceptance gate + `provides_acceptance`/`bind`/`acceptance_adapter` + state fields + TUI card surfacing.
- Review loop: Pass 1 `pm-plan-checker`, Pass 2 `code-review`.
- Post-coding doc handoff (`pm-architect`): architecture.md + user-journeys.md + threat-model.md per plan "Docs to update".
- Update `.ai-pm/contracts/run-plan.md` Must-not-break; append feature to contract Built/changed-by; regenerate `docs/product-map.md`; mark v0.14 progress in docs/plan.md.
- Verify the feature's own acceptance criterion: `notes_cli` 3/3 task_solved (manual outcome probe).
- Ship: pr-prep + PR (manual merge by PM).
- Later features: self-fix-loop (3), acceptance-spec-in-tasks (4), node-cli-adapter (5).

## Touched files

(to be filled by coder) — expected: code_scalpel/plan_runner.py (new), code_scalpel/agent.py (run_plan delegation), code_scalpel/skills/base.py (provides_acceptance + bind), code_scalpel/skills/python_cli_adapter.py (bind override + provides_acceptance), code_scalpel/skills/registry.py (acceptance_adapter), code_scalpel/state.py (run-smoke fields), tests/*.

## Next step

hand off to pm-coder.

## Validation

Per plan Test plan. Pipeline: pytest / ruff check / ruff format --check / mypy code_scalpel/. Feature acceptance: notes_cli 3/3 task_solved (manual probe).

## Notes

Project adopted the protocol over an existing mature codebase (v0.12.5.dev1, v0.14 open in docs/plan.md §31). docs/plan.md remains the long-range design narrative. Autonomous mode active for this batch ("на автомате") — per-feature override line in the plan.

---

## How to use this file

- **Agent step 1** — read this file before doing anything else. If it says "done", do not start work without explicit PM instruction to start a new task.
- **Agent step last** — overwrite this file with the new state before stopping.
- **Session restart** — re-read this file. It should be enough to continue without scrolling chat history.
- **Task complete** — copy this file to `.ai-pm/state/archive/<topic>-<YYYY-MM-DD>.md` and reset this one to a new task or to "Status: idle".
