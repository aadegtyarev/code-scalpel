# project-adapter-abstraction — Pass-1 plan-compliance review

## Plan compliance

### Scenarios (all 11)
- ✓ Scenario 1 — `Skill` ABC gains 4 non-abstract methods with safe defaults (`base.py:142-180`). Test: `test_existing_skills_still_instantiate` + `test_base_defaults` (`tests/test_python_cli_adapter.py:35-70`).
- ✓ Scenario 2 — `PythonCliAdapter.detect` reuses PythonSkill's manifest heuristic (`python_cli_adapter.py:56-59`). Test: `test_python_cli_adapter_detect`.
- ✓ Scenario 3 — `build_install()` → `["pip","install","-e","."]`; `test()` reuses `PythonSkill.test_cmd` verbatim (`python_cli_adapter.py:61-73`). Tests: `test_python_cli_adapter_build_install`, `test_python_cli_adapter_test_matches_python_skill`.
- ✓ Scenario 4 — `run_smoke(args)` → `python -m <pkg> <args>` with `<pkg>` resolved deterministically via `resolve_pkg` (`python_cli_adapter.py:75-86`, `python_pkg.py`). Tests: `test_python_cli_adapter_run_smoke`, `test_run_smoke_pkg_resolution`.
- ✓ Scenario 5 — `scaffold(spec)` emits `src/<pkg>/__init__.py` + `__main__.py` + hatchling src-layout `pyproject.toml` (`python_cli_adapter.py:95-123`). Test: `test_scaffold_smoke` (real execution).
- ✓ Scenario 6 — `acceptance_spec(task)` returns the built-in default-floor `(command, expected)` (`python_cli_adapter.py:88-93`). Test: `test_acceptance_spec_default_floor`.
- ✓ Scenario 7 — registered explicitly with `provides_test_runner = False`, discoverable but not test-runner (`__init__.py:96-103`, `python_cli_adapter.py:46`). Test: `test_registry_default_runner_unchanged_after_adapter_registered`.
- ✓ Scenario 8 (failure path) — `_ensure_absent` clobber-guard fires BEFORE any write; raises `FileExistsError` (`python_cli_adapter.py:114-131`). Test: `test_scaffold_does_not_clobber` (asserts sentinel preserved).
- ✓ Scenario 9 (failure path) — invalid/empty pkg name → `ValueError` before any write (`python_cli_adapter.py:103-107`). Test: `test_scaffold_invalid_pkg_name` (parametrized over `"", "1bad", "has-dash", "has space", "a.b"`; asserts nothing written).

### Contracts (Skill ABC superset)
- ✓ `build_install() -> list[str]`, default `[]` — honored (`base.py:144`).
- ✓ `run_smoke(args="") -> list[str]`, default `[]` — honored (`base.py:153`).
- ✓ `scaffold(spec) -> list[Path]`, default no-op `[]`; `ScaffoldSpec` carries `root` + `pkg` — honored (`base.py:35-44`, `162`).
- ✓ `acceptance_spec(task) -> tuple[...] | None`, default `None` — honored (`base.py:171`).
- ✓ Non-abstract invariant — all four have bodies; `test_existing_skills_still_instantiate` proves no existing skill became abstract; full suite (1221 passed) confirms registry still populates.

### Stack expectations
- ✓ hatchling src-layout `packages = ["src/<pkg>"]` emitted (`_pyproject_template`, `python_cli_adapter.py:160-174`). Test: `test_scaffold_pyproject_has_src_layout_wheel_target` asserts exact `["src/notes_cli"]`.
- ✓ `python -m <pkg>` requires `__main__.py` — scaffold emits it; `run_smoke` targets a `-m`-runnable module. **Stack-spec / execution test** `test_scaffold_smoke` actually runs `subprocess.run([sys.executable,"-m","notes_cli","--help"])` against the scaffolded temp project and asserts `returncode == 0` — verifies behavior against the cited rules, not a self-consistent stand-in. Comment cites both source URLs (Python `__main__`/runpy + hatchling build config), satisfying the plan's "comment must cite the stack-notes source URLs" requirement.
- ✓ pytest flags unchanged — `test()` delegates to `PythonSkill.test_cmd`. Test: `test_python_cli_adapter_test_matches_python_skill` proves no drift (`test()`, `test("-k foo")`, `test_cmd()` all equal PythonSkill).

### Interaction scenarios (shared state: process-global SkillRegistry)
- ✓ `default_runnable(root)` unchanged after adapter registered — `test_registry_default_runner_unchanged_after_adapter_registered` drives the **production** module-level `default_runnable_skill` / `get_skill` (not a hand-built registry), asserts `runnable.name == "python"` and `runnable.test_cmd() == PythonSkill().test_cmd()`, and confirms the adapter is discoverable via `get_skill("python-cli")` with `provides_test_runner is False`. The no-hijack mechanism is real: `registry.default_runnable` filters on `provides_test_runner` (`registry.py:64`); PythonSkill (priority 10) wins. **Test-wiring-parity satisfied** — the test exercises the same registration path production uses (import-time `_registry.register(PythonCliAdapter())`).
- ✓ All existing skills still instantiate after ABC gains methods — `test_existing_skills_still_instantiate` (Python/Go/JS/Docker/Postgres/SQLite); Markdown skills + full suite green confirm registry population unchanged.

### Out of scope — confirmed NOT touched
- ✓ Pure-additive. Code diff is confined to `code_scalpel/skills/` (base, python_cli_adapter [new], python_pkg [new], __init__) + the test file. No `agent.py`, `run_plan`, `runtime.py`, `code_with_retry`, `tools/`, `tui/`, or verification touched (grep clean).
- ✓ `python_pkg.py` (+79, not in the briefed file list) is an in-scope additive helper backing scenario 4's deterministic `<pkg>` resolution — not scope creep.
- ✓ No task-declared `Acceptance:` field, no narrow-pass derivation, no self-fix loop, no sibling adapters, no agent.py decomposition.

### Product Contract
No Product Contract touched — this is a backend-only internal API on the `Skill` ABC (plan states "no user-facing contract"). The adapter is inert: no run-loop consumes it. No user-visible behavior changes.

### Security surfaces
Security-bearing project (`docs/threat-model.md` present). This additive contract-only feature does not wire into any live input/command/parser path (explicitly out of scope), and the one input it does handle — the scaffold package name — is defensively validated (`_PKG_NAME_RE`) and guarded against clobbering existing files before any write. No `### Security-relevant surfaces` item is meaningfully touched; threat-model update not required for this feature.

## Definition of Done
- [x] All plan scenarios implemented and tested (11/11)
- [x] Interaction scenarios have concurrent/shared-state tests (production registry path driven)
- [x] Stack expectations respected; stack-spec test (`test_scaffold_smoke`) passes with cited URLs
- [x] Product Contract — n/a (backend-only, no user-facing contract); no silent behavior change
- [x] Pipeline green — `pytest` 1221 passed / 40 skipped; `ruff check` clean; `ruff format --check` clean; `mypy` clean for feature files (only remaining error is pre-existing `tools/files.py:8`, present on base, NOT in this diff — not attributable to this feature)
- [x] State file updated (`.ai-pm/state/current.md`)
- [ ] Product Impact Report — n/a (no contract touched)
- [x] Docs updates landed — plan lists only `docs/architecture.md` as a **post-coding pm-architect handoff**; correctly deferred, not a coder obligation for this branch
- [x] Expected artifacts exist (plan, this review; no contract required — backend-only)
- [x/n/a] Product-readiness gate — n/a: not user-facing (every scenario subject is the system / ABC / adapter / registry, not a human role)
- [x/n/a] Validation gate — n/a (software-kind project)
- [x] Failure-inventory negative-space tests present — scenarios 8 & 9 each have a dedicated failure-path test

**DoD: pass**

## Blocking
(none)

## Notes (product)
1. The architecture-doc update (ProjectAdapter decision + file-layout entries) is a deferred post-coding `pm-architect` handoff per the plan, not landed on this branch. This is plan-conformant, but worth confirming the orchestrator spawns `pm-architect` before/at ship so `docs/architecture.md` doesn't drift behind the shipped contract. Why it matters: the contract now exists in code but the AS-IS architecture doc won't describe it until that handoff runs.

## Verdict
approve

<!-- The trail below is the ONE review section the orchestrator owns, not pm-plan-checker. -->
## Code review findings
Pass-2 technical review (code-review skill, high effort: 7 finder angles → verify). Verified against the live production registry.

### Blocking (fix before ship)

1. **Adapter leaks into the model-facing catalog, the detected-stack hint, and `/skills` — not just `default_runnable`.** `code_scalpel/skills/__init__.py:103` registers `PythonCliAdapter()` into the global registry. Verified at runtime: `active_skills(python_root) == ['python', 'python-cli']` and `all_skills()` (the model catalog at `agent.py:1881`) now includes `python-cli`. There is **no** `prompts/skills/python-cli.md`, so if the weak model does `load_skill('python-cli')` it gets empty `model_instructions()` — a silent quality regression on the core Python use case (it misses `python.md`'s pytest/ruff guidance). Also surfaces a confusing duplicate Python row in the `/skills` TUI (`tui/app.py:547,607`) and the detected-stack hint (`agent.py:1883,2645`). The plan's interaction scenario only constrained `default_runnable`; "discoverable" was intended as `get_skill`/registry-discoverable, not model-catalog-advertised. **Fix:** keep `python-cli` out of the model catalog / `active_skills` listing / `/skills` panel / detected-stack hint while remaining `get_skill`-discoverable (e.g. an explicit hidden/discovery-only trait honored by the listing sites). Add a test asserting `'python-cli'` is NOT in the model catalog / active listing for a Python project, and IS still returned by `get_skill('python-cli')`.

2. **`acceptance_spec` returns an unresolved `<pkg>` placeholder.** `python_cli_adapter.py` `acceptance_spec` returns `("python -m <pkg> --help", "")` — the literal token `<pkg>`, never substituted, even when the adapter is root-bound (`self._root` set, the same source `run_smoke` resolves via `resolve_pkg`). The test only asserts the substrings `"python -m"` / `"--help"`, so it green-lights a non-runnable command — a latent trap for the next feature (acceptance-gate). **Fix:** when root-bound, resolve `<pkg>` (mirror `run_smoke`); for the rootless singleton either raise like `run_smoke` does or return `None`. Strengthen the test to assert a resolved package name in the root-bound case.

3. **`run_smoke` argument splitting diverges from `test_cmd`.** `run_smoke` uses `args.split()` while `PythonSkill.test_cmd` (which the adapter reuses) uses `shlex.split()`. `run_smoke("--note 'a b'")` → `['--note', "'a", "b'"]` (mangled), while `test_cmd` parses the same string correctly. Both the ABC `run_smoke` docstring and `test_cmd` docstring claim "whitespace-split like test_cmd" — false. **Fix:** use `shlex.split` in `run_smoke`; correct the two docstrings.

### Non-blocking cleanups (apply in the same pass)

4. **`priority = 15` is inert and misleading.** With `provides_test_runner = False` and explicit (non-`*_skill.py`) registration, the auto-scanner never sorts this adapter by `priority`, and `default_runnable` skips it entirely — so `priority` can never affect ordering. Reads as if it competes with `PythonSkill` (priority 10) when it structurally cannot. Remove it, or comment that it is intentionally inert while non-runnable.

5. **Fresh `PythonSkill()` per call.** `detect`/`test_cmd`/`lint_cmd` each construct a throwaway `PythonSkill()` on every invocation (and `detect` runs on every registry lookup). Hold one instance (`self._py = PythonSkill()` in `__init__`, or a module-level singleton) and delegate to it.

6. **`test()` alias has no consumers and is not on the ABC.** `test()` is a one-line alias of `test_cmd()` declared only on the subclass; nothing calls it and the base contract names `test_cmd`. Drop it (or, if a ProjectAdapter run-loop will standardize on `test()`, that belongs on the base — out of scope here).

### Noted, not fixing this feature
- `resolve_pkg` single-`src/`-candidate fallback can return a package lacking `__main__.py` (non-runnable `python -m`). Accepted: it returns the honest package name; runnability is `scaffold`'s concern, not resolution's. Revisit if the acceptance-gate feature needs a runnability guarantee here.
- `_from_pyproject` trusts the declared hatchling wheel target over the filesystem and `Path(entry).name` collapses nested entries. Low-likelihood layouts; acceptable for the default-floor.

**Orchestrator decision:** findings 1–3 block ship and are routed to `pm-coder`; 4–6 bundled into the same fix pass. The two noted items are deferred by decision (recorded above).

## Code review: 2026-06-06 — passed

All Pass-2 findings closed in commit `b08913b`:
- Findings 1–3 (blocking) — fixed and verified on the live production registry: `active_skills(python_root) == ['python']` (no leak), `all_skills()` catalog excludes `python-cli`, `default_skill`/`default_runnable_skill` still resolve to `PythonSkill`, `get_skill('python-cli')` still returns the adapter. `acceptance_spec` resolves `<pkg>` when root-bound (raises like `run_smoke` when rootless); `run_smoke` uses `shlex.split` with corrected docstrings.
- Findings 4–6 (cleanups) — inert `priority` removed; single `PythonSkill` instance held; `test()` alias dropped.
- Mechanism for finding 1: a `hidden` trait on `Skill` honored by the registry listing methods (`all()`/`active()`) only; selection methods (`get`/`default`/`default_runnable`) unchanged.

Pipeline green: pytest 1226 passed / 40 skipped, ruff check + format clean, mypy clean (excluding the pre-existing `code_scalpel/tools/files.py:8` unused-type-ignore present on base main).
