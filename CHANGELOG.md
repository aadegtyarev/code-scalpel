# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

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
