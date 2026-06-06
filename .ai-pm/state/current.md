# Execution state

Single source of truth for the currently active task. Overwritten as the task progresses; archived to `.ai-pm/state/archive/<topic>-<YYYY-MM-DD>.md` on completion.

PM reads this when curious about progress; PM never edits it. Agents read it as their first step and update it as their last step.

---

## Task

Implement feature 1 of the backend redesign: `feat/project-adapter-abstraction` — extend the `Skill` ABC into a ProjectAdapter contract (scaffold / build_install / run_smoke / acceptance_spec) and ship `PythonCliAdapter`. Pure-additive; no run-loop change. Plan: `docs/features/project-adapter-abstraction_plan.md`.

## Status

implementation complete — ready for review

## Done

- Bootstrap: legacy adoption (full documentation mode) completed.
- Spike: diagnosed "doesn't work as a product" — 19% task_solved across 107 probe runs; root cause = no acceptance/run gate in Definition-of-Done. Language-agnostic.
- pm-architect arch note written: `.ai-pm/arch/backend-redesign_arch.md`.
- **feat/project-adapter-abstraction implemented (this task):**
  - `Skill` ABC gained 4 non-abstract ProjectAdapter methods with safe defaults (`build_install`→`[]`, `run_smoke`→`[]`, `scaffold`→`[]` no-op, `acceptance_spec`→`None`) + `ScaffoldSpec` dataclass. No existing skill became abstract.
  - `PythonCliAdapter` (`code_scalpel/skills/python_cli_adapter.py`): detect (=PythonSkill), `build_install`→`pip install -e .`, `test()`==PythonSkill.test_cmd, `run_smoke`→`python -m <pkg>` (pkg resolved deterministically), `scaffold` (src-layout skeleton, clobber-guard + invalid-name guard), `acceptance_spec` default-floor.
  - Deterministic package resolution helper `code_scalpel/skills/python_pkg.py`.
  - Registration decision: adapter registered EXPLICITLY in `__init__.py` (module not named `*_skill.py`, so not auto-discovered) with `provides_test_runner = False` → discoverable via get_skill/all_skills, never selected by `default_runnable` (no test-path hijack). Proven by `test_registry_default_runner_unchanged_after_adapter_registered`.
  - Full Test plan written in `tests/test_python_cli_adapter.py` incl. execution test `test_scaffold_smoke` (runs `python -m <pkg>` against scaffolded temp project).

## Remaining

- Pass 1 review (pm-plan-checker) + Pass 2 (code-review).
- pm-architect post-coding doc update (docs/architecture.md: ProjectAdapter decision + file-layout) — per plan "Docs to update" handoff.
- Later features: feat/acceptance-gate-run-plan (2), self-fix-loop (3), acceptance-spec-in-tasks (4), node-cli-adapter (5).

## Touched files

- code_scalpel/skills/base.py (ScaffoldSpec + 4 new methods)
- code_scalpel/skills/python_cli_adapter.py (new)
- code_scalpel/skills/python_pkg.py (new)
- code_scalpel/skills/__init__.py (explicit registration + exports)
- tests/test_python_cli_adapter.py (new)

## Next step

review (Pass 1 plan-compliance, then Pass 2 technical).

## Validation

pytest: 1221 passed, 40 skipped (full suite). ruff check + ruff format --check: clean on touched files. mypy code_scalpel/skills/: clean. KNOWN PRE-EXISTING (not this diff): `mypy code_scalpel/` reports 1 error in `code_scalpel/tools/files.py:8` (unused type:ignore) present on the base commit — surfaced, not papered over.

## Notes

Project adopted the protocol over an existing mature codebase (v0.12.5.dev0, v0.14 open in docs/plan.md §31). docs/plan.md remains the long-range design narrative.

---

## How to use this file

- **Agent step 1** — read this file before doing anything else. If it says "done", do not start work without explicit PM instruction to start a new task.
- **Agent step last** — overwrite this file with the new state before stopping.
- **Session restart** — re-read this file. It should be enough to continue without scrolling chat history.
- **Task complete** — copy this file to `.ai-pm/state/archive/<topic>-<YYYY-MM-DD>.md` and reset this one to a new task or to "Status: idle".
