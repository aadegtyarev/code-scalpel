# Execution state

Single source of truth for the currently active task. Overwritten as the task progresses; archived to `.ai-pm/state/archive/<topic>-<YYYY-MM-DD>.md` on completion.

PM reads this when curious about progress; PM never edits it. Agents read it as their first step and update it as their last step.

---

## Task

Feature 4 of the backend redesign: `feat/acceptance-spec-in-tasks` — give the observational acceptance gate its teeth. Flip verification #4 to ENFORCING (demote done→failed) gated on `spec.applicable`; add task-declared acceptance + an args-only narrow-pass-derived fallback with write-back; `AcceptanceSpec` dataclass; keep the run-loop language-agnostic. Plan: `docs/features/acceptance-spec-in-tasks_plan.md`. Arch: `.ai-pm/arch/acceptance-spec-in-tasks_arch.md`. Decision authority: autonomous.

## Status

coding complete — ready for review loop. Pipeline green (1271 passed / 40 skipped, ruff + format clean, mypy clean) EXCEPT one pre-existing, unrelated mypy error in code_scalpel/tools/files.py:8 (unused `# type: ignore`) that already exists on the base commit c518078 in untouched code — surfaced, NOT papered over. Cause: local pathspec 0.12.1 ships py.typed, so the bare ignore is now unused; an environment discrepancy, not a feature regression.

## Done

- Features 1 (PR #168) + 2 (PR #169) merged. Acceptance run-smoke plumbing is in main, observational (never demotes).
- **Planning:**
  - PM decisions captured: (a) **generality** — NOT a notes_cli/python special case; run-loop carries zero language strings, all run-strings come from the detect()-selected adapter; (b) **args-only** model-derived checks (model returns {applicable,args,expected}; adapter builds the argv; no free-form shell).
  - Focused `pm-architect` arch note; plan (8 scenarios + 4 failure paths; KD1–KD6); product-readiness gate clean.
- **Coding (this task) — commits 27ca34c, 4a0dbb0, c986f36:**
  - `AcceptanceSpec(command,expected,applicable,source)` frozen dataclass + encode/decode_derived_acceptance helpers (skills/base.py); `Skill.acceptance_spec` return type tuple→AcceptanceSpec|None.
  - PythonCliAdapter precedence B (declared) → C (derived marker) → A (floor); every branch builds command via run_smoke(args); floor never applicable (regression lock).
  - plan_verify verification #4 flipped to ENFORCING gated on spec.applicable; pkg-unresolvable applicability read from the task (failure-path 12); no language string in the loop path (audited).
  - Args-only narrow-pass derivation pre-loop (plan_loading._derive_acceptance, beside _annotate_plan) with output_schema {applicable,args,expected}; write-back to TASKS.json canonical + re-rendered/re-hashed markdown sentinel; typed tasks returned (finding 7); LLM/parse error→floor (path 9), disk error→in-memory+old sentinel (path 10). New config auto_derive_acceptance. derive_acceptance.md prompt + DERIVE_ACCEPTANCE export. agent.derive_acceptance_args + _DERIVE_ACCEPTANCE_SCHEMA.
  - state.last_acceptance_source persisted (forward-compatible default).
  - Tests: tests/test_acceptance_enforcement.py (22 new) — enforcement, generality (non-python adapter), args-only no-injection, derivation+write-back+resume, failure paths 9/10/12, json_schema + argv-no-shell stack-spec, interaction (plan_modified, compose, yolo-on-skeptic). Feature-2 tuple-shape + "never demotes for applicable" assertions updated per the planned contract change.

## Remaining

- Review loop: Pass 1 `pm-plan-checker`, Pass 2 `code-review`.
- Post-coding doc handoff (`pm-architect`): architecture.md + user-journeys.md + threat-model.md + plan.md per "Docs to update". Contract `run-plan.md` Must-not-break update.
- Verify feature acceptance: `notes_cli` 3/3 task_solved (manual outcome probe, Step 5.5) BEFORE ship.
- Ship: pr-prep + PR (merge authorized by PM for this batch).
- Later: feature 3 (self-fix-loop), feature 5 (node-cli-adapter).

## Touched files

- code_scalpel/skills/base.py — AcceptanceSpec dataclass + encode/decode_derived_acceptance; acceptance_spec return type
- code_scalpel/skills/python_cli_adapter.py — precedence B→C→A via run_smoke(args)
- code_scalpel/plan_verify.py — enforce-iff-applicable + _task_acceptance_applicable + source plumbing
- code_scalpel/plan_loading.py — _derive_acceptance pre-pass + write-back (JSON canonical, re-hash-safe)
- code_scalpel/agent.py — derive_acceptance_args + _DERIVE_ACCEPTANCE_SCHEMA
- code_scalpel/prompts/derive_acceptance.md (+ prompts/__init__.py export)
- code_scalpel/config.py — auto_derive_acceptance flag
- code_scalpel/state.py — last_acceptance_source field
- tests/test_acceptance_enforcement.py (new), tests/test_acceptance_gate.py, tests/test_python_cli_adapter.py, tests/test_agent.py

NOT touched (per task): docs/*, .ai-pm/contracts/run-plan.md, plan.md — post-coding pm-architect doc handoff. Feature 3 (self-fix) and feature 5 (node adapter) deferred.

## Next step

review loop (Pass 1 pm-plan-checker; Pass 2 code-review). Then doc handoff + notes_cli 3/3 outcome probe before ship.

## Out-of-scope findings (→ backlog)

- code_scalpel/tools/files.py:8 — pre-existing `# type: ignore` is unused under pathspec 0.12.1 (ships py.typed); mypy flags it. Exists on base commit, unrelated to this feature. Either drop the ignore or pin pathspec; PM/maintainer call.

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
