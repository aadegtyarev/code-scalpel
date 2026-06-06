# Execution state

Single source of truth for the currently active task. Overwritten as the task progresses; archived to `.ai-pm/state/archive/<topic>-<YYYY-MM-DD>.md` on completion.

PM reads this when curious about progress; PM never edits it. Agents read it as their first step and update it as their last step.

---

## Task

Implement feature 1 of the backend redesign: `feat/project-adapter-abstraction` — extend the `Skill` ABC into a ProjectAdapter contract (scaffold / build_install / run_smoke / acceptance_spec) and ship `PythonCliAdapter`. Pure-additive; no run-loop change. Plan: `docs/features/project-adapter-abstraction_plan.md`.

## Status

Pass-2 review findings 1–6 addressed — ready for re-review

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
- **Pass-2 review fixes (this task) — findings 1–6:**
  - (1, blocking) Added `hidden: bool = False` trait on `Skill`; `SkillRegistry.all()`/`active()` now exclude hidden skills while `get()`/`default()`/`default_runnable()` keep their unfiltered scan. `PythonCliAdapter.hidden = True` → out of model catalog / detected-stack hint / `/skills` panel, still `get_skill('python-cli')`-discoverable. No other skill affected.
  - (2, blocking) `acceptance_spec` resolves the real package via `resolve_pkg(self._root)` when root-bound; raises the same clear "project root" error as `run_smoke` for the rootless singleton — no more literal `<pkg>` placeholder.
  - (3, blocking) `run_smoke` now uses `shlex.split` (parity with `test_cmd`); ABC `run_smoke` + `test_cmd` docstrings corrected to say "split with shlex".
  - (4) Removed inert `priority = 15` from the adapter.
  - (5) Adapter holds a single `self._py = PythonSkill()`; `detect`/`test_cmd`/`lint_cmd` delegate to it.
  - (6) Dropped the `test()` alias (kept `test_cmd`); updated the new-on-branch test that referenced it.
  - New tests: hidden-from-listings + discoverable, default_skill/default_runnable regression guard, hidden-trait isolation, shlex-split run_smoke, root-bound + rootless acceptance_spec.

## Remaining

- Pass 2 re-review of the fix pass (code-review).
- pm-architect post-coding doc update (docs/architecture.md: ProjectAdapter decision + file-layout) — per plan "Docs to update" handoff.
- Later features: feat/acceptance-gate-run-plan (2), self-fix-loop (3), acceptance-spec-in-tasks (4), node-cli-adapter (5).

## Touched files

- code_scalpel/skills/base.py (ScaffoldSpec + 4 new methods + `hidden` trait + docstring fixes)
- code_scalpel/skills/registry.py (all()/active() honor `hidden`)
- code_scalpel/skills/python_cli_adapter.py (new; Pass-2 fixes 2–6)
- code_scalpel/skills/python_pkg.py (new)
- code_scalpel/skills/__init__.py (explicit registration + exports)
- tests/test_python_cli_adapter.py (new + Pass-2 fix tests)

## Next step

re-review (Pass 2 technical re-check of the fix pass).

## Validation

pytest: 1226 passed, 40 skipped (full suite; +5 new tests). ruff check + ruff format --check: clean. mypy code_scalpel/: clean except the KNOWN PRE-EXISTING (not this diff) error in `code_scalpel/tools/files.py:8` (unused type:ignore) present on the base commit — confirmed via stash, surfaced not papered over.

## Notes

Project adopted the protocol over an existing mature codebase (v0.12.5.dev0, v0.14 open in docs/plan.md §31). docs/plan.md remains the long-range design narrative.

---

## How to use this file

- **Agent step 1** — read this file before doing anything else. If it says "done", do not start work without explicit PM instruction to start a new task.
- **Agent step last** — overwrite this file with the new state before stopping.
- **Session restart** — re-read this file. It should be enough to continue without scrolling chat history.
- **Task complete** — copy this file to `.ai-pm/state/archive/<topic>-<YYYY-MM-DD>.md` and reset this one to a new task or to "Status: idle".
