# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

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
