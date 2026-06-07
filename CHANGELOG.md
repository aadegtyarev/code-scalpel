# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.12.5.dev5] — 2026-06-07
### Added
- Flat-layout run-smoke. The acceptance gate can now find and run the CLI of a
  flat-layout Python project — one where the package sits at the repo root
  rather than under `src/`. It recognises three shapes, in a fixed order of
  preference: a root package with a `__main__.py` (run as `python -m pkg`), a
  single root entry script such as `cli.py` / `main.py` / `__main__.py` (run
  directly), and a single declared console command from `[project.scripts]`. A
  declared console command always wins over a discovered script; if the project
  is ambiguous or has no runnable entry, the gate raises rather than guessing.
  This closes the first of the two reach gaps that left the acceptance gate and
  the self-fix loop inert on the canonical flat-layout scenario.
- New config `run_smoke_script_candidates` lets you set which root script names
  count as entry points; the values are validated against path traversal.
### Changed
- The acceptance gate now verifies the runnable CLI at the **last task that
  actually builds it**, not merely the last task in the plan. So a CLI finished
  before the final task — for example when the plan ends with a tests-only or
  docs-only task — is still run-smoked, and a failing run-smoke still engages
  the self-fix loop at trust `optimist` / `yolo`. This closes the second reach
  gap. No new task status is introduced, and both existing safety invariants
  hold: an early task is never demoted, and a library (no-CLI) project is never
  failed by this gate.

## [0.12.5.dev4] — 2026-06-07
### Added
- Bounded, trust-gated acceptance self-fix loop. When a runnable CLI
  deliverable's acceptance run-smoke fails on the last applicable task, the
  agent no longer demotes `done → failed` straight away: at trust `optimist`
  or `yolo` it feeds the failing run-smoke output back to the model, rebuilds,
  and re-runs the smoke — up to a bounded budget — before finally failing. At
  `skeptic` it fails immediately and waits for the human, as before.
- The failing run-smoke output is now carried inline into the self-fix attempt,
  so the model sees exactly what broke instead of a bare verdict.
- New config: `acceptance_self_fix` (bool, default **on**) gates the loop, and
  `acceptance_self_fix_max_attempts` (int, default **3**) caps the retries.
### Changed
- Self-fix is **bounded twice over**: by the attempt budget and by an
  identical-run-smoke-output anti-loop early-stop — if a rebuild produces the
  same failing output, the loop stops early rather than burning the budget.
- Self-fix fires only at the single last-applicable-task position; early CLI
  tasks and library / no-spec tasks are never self-fixed, so the blast radius
  of the retry behaviour stays exactly where acceptance enforcement already is.

## [0.12.5.dev3] — 2026-06-06
### Added
- Acceptance specs in tasks — the acceptance gate now has teeth. A task can
  carry a typed `AcceptanceSpec(command, expected, applicable, source)`, and
  the run loop's verification #4 now **enforces** it: when an *applicable* spec
  exists and the deliverable fails to satisfy it, the task is demoted
  `done → failed`. Previously the run-smoke verdict was observational only.
- Args-only acceptance derivation: a narrow pre-loop pass asks the model only
  for `{applicable, args, expected}` and the adapter builds the argv from it —
  no free-form shell is ever derived or executed (security decision). The
  derived spec is written back into the plan. A human-declared prose acceptance
  criterion is treated as a **hint** to this derivation, not executed directly.
- `auto_derive_acceptance` config flag (default **on**) to gate the derivation
  pass.
### Changed
- Enforcement is **applicable-gated**: only deliverables with an applicable
  acceptance spec can be failed by the gate. The `applicable` flag is the
  CLI-vs-library discriminator — the default floor never sets it, so libraries
  and projects without a spec are never wrongly failed (no regression to the
  prior observational behaviour).
- The run loop is now **language-agnostic**: it carries zero language-specific
  strings, so a future adapter (e.g. Node) plugs in without any run-loop edit.

## [0.12.5.dev2] — 2026-06-06
### Added
- Run-smoke plumbing and observability in `run_plan`: after a plan finishes,
  the run loop resolves an acceptance adapter from the skill registry and runs
  the deliverable's run-smoke (`python -m <pkg> --help`), then records and
  surfaces the verdict — whether the deliverable actually ran. This is
  **observational only**: the verdict is reported but never demotes a task to
  `failed`, so there is **no change to which tasks pass or fail** in this
  release. Enforcement (acting on the verdict) is deferred to a later feature,
  because acting on it first requires a reliable CLI-vs-library signal to know
  what "ran" means for a given deliverable.
- Acceptance-adapter mechanism on the skill layer: `Skill.provides_acceptance`,
  `Skill.bind(root)`, and `SkillRegistry.acceptance_adapter` let the run loop
  discover and bind the adapter that knows how to run-smoke a deliverable.
- `AgentState` run-smoke fields to carry the recorded verdict through the run.
### Changed
- Strangled `run_plan` out of the monolithic `agent.py` into focused modules —
  `plan_runner.py`, `plan_loading.py`, `plan_post_checks.py`, and
  `plan_verify.py`. Behavior-preserving refactor, no functional change.

## [0.12.5.dev1] — 2026-06-06
### Added
- ProjectAdapter contract: extends the `Skill` ABC with four non-abstract
  methods (`build_install`, `run_smoke`, `scaffold`, `acceptance_spec`) plus a
  `ScaffoldSpec` value type, and ships the first implementation,
  `PythonCliAdapter`. Pure-additive and inert — the contract is defined and
  registered but not yet wired into the run loop (that is the next feature), so
  there is no behaviour change in this release.
- Registry `hidden` trait: an adapter registered as hidden is discoverable via
  `get_skill` but is not advertised in the model catalog, `active_skills`, or
  `/skills`. This keeps the new adapter available to internal callers while
  remaining invisible to the model until the run-loop consumer lands.
