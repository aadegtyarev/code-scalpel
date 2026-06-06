# Execution state

Single source of truth for the currently active task. Overwritten as the task progresses; archived to `.ai-pm/state/archive/<topic>-<YYYY-MM-DD>.md` on completion.

PM reads this when curious about progress; PM never edits it. Agents read it as their first step and update it as their last step.

---

## Task

Feature 4 of the backend redesign: `feat/acceptance-spec-in-tasks` — give the observational acceptance gate its teeth. Flip verification #4 to ENFORCING (demote done→failed) gated on `spec.applicable`; add task-declared acceptance + an args-only narrow-pass-derived fallback with write-back; `AcceptanceSpec` dataclass; keep the run-loop language-agnostic. Plan: `docs/features/acceptance-spec-in-tasks_plan.md`. Arch: `.ai-pm/arch/acceptance-spec-in-tasks_arch.md`. Decision authority: autonomous.

## Status

planning complete — ready for coder handoff

## Done

- Features 1 (PR #168) + 2 (PR #169) merged. Acceptance run-smoke plumbing is in main, observational (never demotes).
- **This task (planning):**
  - PM decisions captured: (a) **generality** — NOT a notes_cli/python special case; run-loop carries zero language strings, all run-strings come from the detect()-selected adapter; (b) **args-only** model-derived checks (model returns {applicable,args,expected}; adapter builds the argv; no free-form shell).
  - Focused `pm-architect` arch note: `AcceptanceSpec(command,expected,applicable,source)` dataclass (overrules the tuple); enforce iff `spec.applicable`; floor never sets applicable (regression lock); args-only schema; write-back JSON-canonical; T11 provenance resolved + residual risk surfaced.
  - Plan written (8 scenarios + 4 failure paths; KD1–KD6 + residual-risk; contracts; stack expectations; interaction scenarios; full test plan incl. a non-python adapter generality test; docs-to-update; out-of-scope).
  - Product-readiness gate (`pm-product-advocate`): **clean**.

## Remaining

- Coder: implement on `feat/acceptance-spec-in-tasks` — `AcceptanceSpec`; `Skill.acceptance_spec(task)->AcceptanceSpec|None`; PythonCliAdapter precedence B→C→A; the args-only narrow-pass derivation + write-back (pre-loop, beside skill annotation, re-hash-safe); flip `plan_verify._verify_acceptance` to enforce iff applicable; update all current `acceptance_spec` call sites + the feature-2 tests that asserted "never demotes". Keep the run-loop language-agnostic (generality test).
- Review loop: Pass 1 `pm-plan-checker`, Pass 2 `code-review`.
- Post-coding doc handoff (`pm-architect`): architecture.md + user-journeys.md + threat-model.md + plan.md per "Docs to update". Contract `run-plan.md` Must-not-break update.
- Verify feature acceptance: `notes_cli` 3/3 task_solved (manual outcome probe, Step 5.5) BEFORE ship.
- Ship: pr-prep + PR (merge authorized by PM for this batch).
- Later: feature 3 (self-fix-loop), feature 5 (node-cli-adapter).

## Touched files

(to be filled by coder) — expected: code_scalpel/skills/base.py (AcceptanceSpec + acceptance_spec signature), python_cli_adapter.py (precedence B→C→A via run_smoke args), plan_verify.py (enforce-iff-applicable), plan_loading.py (derivation pre-pass + write-back), plan.py (acceptance write-back round-trip), narrow_pass usage, state.py (source field?), tests/*.

## Next step

hand off to pm-coder.

## Validation

Per plan Test plan. Pipeline: pytest / ruff check / ruff format --check / mypy code_scalpel/. Feature acceptance: notes_cli 3/3 task_solved (manual probe before ship).

## Notes

Mature codebase (v0.12.5.dev2 after #169, v0.14 open). Autonomous mode for this batch. Security fork (model-derived check trust) was escalated → PM chose args-only. Generality steer from PM: solution is language-agnostic, notes_cli is the proof not the target.

---

## How to use this file

- **Agent step 1** — read this file before doing anything else. If it says "done", do not start work without explicit PM instruction to start a new task.
- **Agent step last** — overwrite this file with the new state before stopping.
- **Session restart** — re-read this file. It should be enough to continue without scrolling chat history.
- **Task complete** — copy this file to `.ai-pm/state/archive/<topic>-<YYYY-MM-DD>.md` and reset this one to a new task or to "Status: idle".
