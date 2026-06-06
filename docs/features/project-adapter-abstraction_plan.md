# project-adapter-abstraction — plan

Source: backend redesign migration step 1, `.ai-pm/arch/backend-redesign_arch.md` (PM-selected first feature).

Backbone for the backend redesign. Extends the existing `Skill` ABC into a **ProjectAdapter** contract (adds `scaffold` / `build_install` / `run_smoke` / `acceptance_spec`) and ships the first concrete adapter, `PythonCliAdapter`. **Pure-additive: no run-loop change.** The acceptance gate that consumes these methods is the *next* feature (`feat/acceptance-gate-run-plan`); this feature only makes the contract exist and proves it with unit tests.

## Scenarios

1. The `Skill` ABC gains four new capability methods — `scaffold`, `build_install`, `run_smoke`, `acceptance_spec` — as **optional methods with safe defaults**, so every existing skill (Python, Go, JS, Docker, Postgres, SQLite, Markdown) keeps instantiating and behaving exactly as before.
2. A `PythonCliAdapter` exists and detects a Python project by the same manifest heuristic the current `PythonSkill` uses (`pyproject.toml` / `requirements.txt` / `setup.py`).
3. `PythonCliAdapter.build_install()` returns the deterministic install command (`pip install -e .`); `PythonCliAdapter.test()` returns the existing Python test command (unchanged from `PythonSkill`).
4. `PythonCliAdapter.run_smoke(args)` returns the command that runs the actual deliverable the way a user would — `python -m <pkg> <args>` — where `<pkg>` is resolved deterministically from the project (not guessed): from the package under `src/` or the project's declared entry module.
5. `PythonCliAdapter.scaffold(spec)` produces a deterministic, runnable Python-CLI skeleton — a `src/<pkg>/` package with `__init__.py`, a `__main__.py` entrypoint, and a `pyproject.toml` whose hatchling config uses the correct src-layout — such that `python -m <pkg>` runs without an import/packaging error. This is what removes the `__main__.py` coin-flip from the model's hands.
6. `PythonCliAdapter.acceptance_spec(task)` returns the **built-in default-floor** spec for a python-cli project (the deliverable is invokable via `python -m <pkg>` and a no-op/`--help` invocation exits cleanly). Task-declared and narrow-pass-derived specs are explicitly deferred (see Out of scope).
7. `PythonCliAdapter` is registered in the skill registry so it is discoverable, **without changing which skill the registry selects as the default test runner** for an existing Python project.

### Failure paths (scaffold touches the filesystem)
8. `scaffold(spec)` against a target that already contains source files does **not** clobber existing user code — it either no-ops on present files or fails loudly with a clear error, never silently overwrites.
9. `scaffold(spec)` with an invalid or empty package name fails with a clear error rather than producing a broken/half-written skeleton.

## Existing behaviors this feature touches

(from `docs/user-journeys.md` + `docs/architecture.md` `### Recipe / skill loading`)
- **The `run_tests` / lint / format resolution via the active skill must not change.** A Python project still resolves to `PythonSkill`'s `pytest`/`ruff` commands; registering `PythonCliAdapter` must not alter `default_runnable` selection or any existing tool behavior.
- **Every existing skill keeps working** — Go/JS/Docker/Postgres/SQLite/Markdown skills must still construct and answer `detect`/`test_cmd`/`lint_cmd` unchanged after the ABC gains new methods.
- `/skills` accounting (`token_cost`) and `model_instructions` loading are unaffected.

## Contracts

(internal API on the `Skill` ABC — backend-only, no user-facing contract)
- `Skill.build_install() -> list[str]` — argv to make the deliverable runnable. Default `[]` (skill provides no install step).
- `Skill.run_smoke(args: str = "") -> list[str]` — argv to run the actual deliverable as a user would. Default `[]` (skill cannot run-smoke).
- `Skill.scaffold(spec) -> <file plan>` — produce a deterministic runnable skeleton for the project type. Default: no-op / not-supported. `spec` carries at least the package name; exact shape is the coder's choice.
- `Skill.acceptance_spec(task) -> tuple[command, expected_observable] | None` — how "actually works" is checked. Default `None` (no acceptance contract). `PythonCliAdapter` returns the built-in default-floor.
- **Invariant:** all four are **non-abstract** with defaults — adding them must not turn any existing concrete skill into an abstract class.

## Stack expectations touched

(from `docs/stack-notes.md`)
- **hatchling / src-layout**: a `src/<pkg>` package must declare `[tool.hatch.build.targets.wheel] packages = ["src/<pkg>"]`, else metadata generation fails. `scaffold()` must emit this correctly. Source: hatchling build-config docs (cited in stack-notes).
- **`python -m <pkg>` invocation contract**: running a package via `-m` requires a `__main__.py` in the package; a `[project.scripts]` console entry alone does **not** make `python -m <pkg>` work. `scaffold()` must produce `__main__.py`; `run_smoke()` must target a module that is actually `-m`-runnable. Source: Python `__main__` / runpy docs (cited in stack-notes).
- **pytest invocation**: `test()` reuses the existing `PythonSkill` flags (`-x --tb=short --no-header -q`) — no change. Source: stack-notes pytest entry.

## Interaction scenarios

Shared state: the process-global `SkillRegistry` (single instance; the agent and TUI both read it).
- **When `PythonCliAdapter` is registered alongside the existing `PythonSkill` and a Python project is opened:** `registry.default_runnable(root)` must return the same test-runner skill as before this feature (no regression in test/lint resolution). The new adapter is discoverable but does not hijack the existing test path.
- **When the ABC gains the four new methods and the registry constructs every built-in skill at import:** all existing skills still instantiate (no new abstractmethod), so registry population is unchanged.

## Test plan

- Existing tests that must pass: **all existing tests** (especially the `skills/` and registry suites).
- New tests:
  - `test_existing_skills_still_instantiate`: Go/JS/Docker/Postgres/SQLite/Markdown skills construct after the ABC gains the new methods — proves the methods are non-abstract with defaults.
  - `test_base_defaults`: a minimal skill not overriding the new methods returns the documented defaults (`build_install() == []`, `run_smoke() == []`, `acceptance_spec() is None`, `scaffold` is a no-op/not-supported).
  - `test_python_cli_adapter_detect`: detects a project root containing `pyproject.toml` (and the other markers); does not detect an empty dir.
  - `test_python_cli_adapter_build_install`: returns `["pip","install","-e","."]`.
  - `test_python_cli_adapter_test_matches_python_skill`: `test()` argv equals the current `PythonSkill.test_cmd()` output (no behavior drift).
  - `test_python_cli_adapter_run_smoke`: `run_smoke("add x")` returns `["python","-m","<pkg>","add","x"]` with `<pkg>` resolved from the project, not hardcoded.
  - `test_run_smoke_pkg_resolution`: given a scaffolded/sample project whose package is `notes_cli`, `run_smoke` targets `notes_cli`, not `src` or a guess.
  - `test_acceptance_spec_default_floor`: returns the documented python-cli default-floor `(command, expected)` tuple shape.
  - `test_scaffold_smoke` (**stack-spec / execution test**): `scaffold` a temp project, then actually run `python -m <pkg>` against it and assert it executes without an import/packaging error — proves the scaffold produces a `-m`-runnable entrypoint (kills the `__main__.py` coin-flip). Comment must cite the stack-notes `__main__`/hatchling source URLs.
  - `test_scaffold_does_not_clobber` (**failure path, scenario 8**): scaffold into a dir with an existing source file → existing file is preserved (no-op or loud error), never overwritten.
  - `test_scaffold_invalid_pkg_name` (**failure path, scenario 9**): invalid/empty package name → clear error, no half-written skeleton.
- Interaction scenario tests:
  - `test_registry_default_runner_unchanged_after_adapter_registered`: register `PythonCliAdapter`, then assert `default_runnable(python_root)` resolves to the same test-runner contract as before (drives the **production registry path**, not a hand-built registry).
- Stack-spec tests: `test_scaffold_smoke` above doubles as the stack-spec test for the hatchling src-layout + `python -m` rules — it verifies behavior against the cited stack-notes rules, not against the coder's own mapping.

## Docs to update

- `docs/architecture.md`: add an Architectural decision — **ProjectAdapter as a superset of `Skill`** (scaffold/build_install/run_smoke/acceptance_spec; deterministic code-owned run contract; first adapter `PythonCliAdapter`) — and the new File-layout entries for the adapter. Updated by `pm-architect` post-coding (per the arch note's "Docs to update" handoff).

## Out of scope

- **Wiring any of this into the run loop.** No change to `run_plan`, `code_with_retry`, `agent.py`, or any verification step. That is `feat/acceptance-gate-run-plan` (feature 2).
- **Task-declared `Acceptance:` field and narrow-pass-derived acceptance spec** (Fork 2 B/C). This feature ships only the built-in default-floor (Fork 2 A); the precise round-trip spec is `feat/acceptance-spec-in-tasks` (feature 4).
- **The self-fix route-back** on acceptance failure — `feat/acceptance-self-fix-loop` (feature 3).
- **Sibling adapters (other project types):**
  - `NodeCliAdapter` / other languages — separate plan (`feat/node-cli-adapter`, step 5); the abstraction must *allow* it without a run-loop edit, but it is not built here.
  - `python-lib` / `python-web` project types — different `run_smoke`/`scaffold` shape (a library has no `python -m` deliverable); separate plans. This feature scopes to **python-CLI** because that is the `notes_cli` benchmark type.
- **Decomposing `agent.py`** — opportunistic later (Fork 3 B); untouched here.
