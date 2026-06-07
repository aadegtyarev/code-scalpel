# Plan-compliance review — flat-layout-run-smoke (Pass 1)

Branch `feat/flat-layout-run-smoke`. Commits `78ae4a4` (Gap A), `afba44c` (Gap B),
`a04c141` (docs + contract handoff). Diff vs `main`. Scope: plan-compliance only.

## Plan compliance

### Scenarios (resolution + enforcement)
- ✓ S1 Flat-layout root package runs — `resolve_pkg` rung 3; test `tests/test_python_pkg.py::test_resolve_root_package_with_main`, argv `tests/test_flat_layout_run_smoke.py::test_run_smoke_module_argv`
- ✓ S2 Flat-layout root script runs — rung 5 (config candidate list); `test_resolve_root_script`, argv `test_run_smoke_script_argv`
- ✓ S3 Console-script entry point runs (declared outranks discovered) — rung 2; `test_resolve_project_scripts_entry` + stack-spec `test_declared_entry_outranks_discovered`
- ✓ S4 src-layout / hatchling unchanged — `test_resolve_src_layout_unchanged`, `test_resolve_hatchling_target_unchanged`
- ✓ S5 Ambiguity still raises — `test_resolve_ambiguous_root_scripts_raises`, `_ambiguous_root_packages_raises`, `_ambiguous_hatchling_target_raises`, `_ambiguous_project_scripts_raises`
- ✓ S6 Deliverable-complete enforcement at last applicable task — `tests/test_flat_layout_run_smoke.py::test_enforce_at_last_applicable_not_last_task` (production `run_plan` path)
- ✓ S7 Early task never demoted (no-regression) — `test_early_cli_task_not_demoted` (production path)
- ✓ S8 Library / no-applicable-spec never failed (no-regression) — `test_library_plan_never_enforced` (production path) + `test_last_applicable_index_no_applicable_is_sentinel`

### Failure paths (negative-space)
- ✓ S9 Malformed / unreadable `pyproject.toml` falls through, no crash — `test_resolve_malformed_pyproject_falls_through`, `test_resolve_unreadable_pyproject_falls_through`
- ✓ S10 No resolvable runnable → `ValueError` → `pkg-unresolvable` — `test_resolve_absence_raises`, `test_resolve_no_runnable_raises_pkg_unresolvable`

### Design decisions honored
- ✓ Q1 Option 1 — `resolve_pkg` returns typed `RunTarget(kind, target)`; deterministic declared-outranks-discovered ladder (`code_scalpel/skills/python_pkg.py:57-89`); argv shape lives in `_argv_prefix` (`python_cli_adapter.py`), no second filesystem read.
- ✓ Q2 Option (a) — enforcement position = new pure `_last_applicable_index` (`plan_runner.py:84`), computed from the existing pure `acceptance_applicable` predicate; only the `should_run_now` derivation moved (one line). `_last_not_done_index` retained as fallback.
- ✓ CRITICAL — `verify_task` + the feature-3 self-fix helpers are byte-for-byte UNCHANGED (the `plan_runner.py` diff touches no `verify_task` / `_self_fix*` / `_acceptance_demoted` / budget / `auto_confirm` line; grep confirmed). Only which task triggers enforcement moved.
- ✓ No magic list — candidate filenames are a typed pydantic field `AgentConfig.run_smoke_script_candidates` (`config.py`), threaded through the adapter; `test_resolve_custom_candidate_list` proves it is config-owned.

### No-regression invariants
- ✓ Early CLI task never demoted — `test_early_cli_task_not_demoted` + by-construction (single enforcing position).
- ✓ Library / no-applicable-spec never failed — `test_library_plan_never_enforced`; `-1` sentinel paths covered (`_no_applicable_is_sentinel`, `_no_adapter_is_sentinel`, `_predicate_raise_observes`).

### Test-wiring-parity
- ✓ `test_self_fix_fires_at_last_applicable`, `test_enforce_at_last_applicable_not_last_task`, `test_early_cli_task_not_demoted`, `test_library_plan_never_enforced`, `test_later_task_not_re_enforced_after_last_applicable` and `test_run_smoke_root_package_through_acceptance_adapter` all drive the production `StepAgent.run_plan` / `acceptance_adapter` registration path — not a hand-rolled gate. The pure-predicate `_last_applicable_index` unit tests use a stand-in, but the end-to-end demotion/self-fix tests exercise the real wiring.

### Stack-spec test
- ✓ `test_declared_entry_outranks_discovered` — `[project.scripts]` chosen over a filesystem root script, entry-points spec URL in the test body. Plus `test_hatchling_outranks_project_scripts`, `test_root_package_outranks_root_script` pin the ladder.

### Interaction scenarios
- ✓ "later task not re-enforced after last-applicable" — `test_later_task_not_re_enforced_after_last_applicable` (production path).
- ✓ "self-fix recovers the CLI at the last-applicable position while later non-CLI tasks remain; later tasks proceed" — `test_self_fix_fires_at_last_applicable` (T001 recovers → done, T002 proceeds → done). The "committed exactly once" sub-property is preserved by the unchanged self-fix mechanism and held by feature-3's `tests/test_acceptance_self_fix.py::test_recovered_task_is_committed`. The plan named a dedicated `test_recovered_cli_committed_once_with_later_tasks`; the property is covered, the exact test name is not present — see note 1.
- ✓ "wider run-smoke reach does not change self-fix bounds" — bounds are byte-for-byte unchanged (helpers untouched); feature-3 bound tests still pass.

### Security surface (security-bearing project)
- ✓ Run-smoke reach widens (a `### Security-relevant surfaces` item). `docs/threat-model.md` was in Docs-to-update and is updated: attack-surface row, T05/T06/T10 reach notes, a dated Review entry (`2026-06-07 for feat/flat-layout-run-smoke`), `Last reviewed: 2026-06-07`. No new boundary; SC7/SC8 reaffirmed — matches the implementation (verb code-owned, args-only, bwrap boundary).

### Docs to update — all landed
- ✓ `docs/architecture.md` — position now "last applicable task"; decision record "Flat-layout run-smoke + deliverable-complete enforcement (v0.14)"; `RunTarget` descriptor noted.
- ✓ `docs/threat-model.md` — as above.
- ✓ `.ai-pm/contracts/run-plan.md` — position wording updated; both `## Out of scope` reach-gap lines cleared (no "reach gap" / "fuller deliverable" out-of-scope lines remain); `## Must work` / `## Acceptance checks` / `## Built/changed by` updated.
- ✓ `docs/plan.md` — §31 progress marked.

### Product Contract
- ✓ `.ai-pm/contracts/run-plan.md` honored. Must-work: flat-layout resolution + last-applicable enforcement now match the implementation. Must-not-break: early-task never demoted + library never failed both tested. Acceptance checks present (flat-layout resolution + last-applicable enforcement rows added). No silent behavior change — the demotion path reuses `done → failed`, taxonomy unchanged.

### No existing test weakened
- ✓ Diff touches only two NEW test files (`tests/test_python_pkg.py`, `tests/test_flat_layout_run_smoke.py`); no existing test file modified.

### Diff-noise
- ✓ No cosmetic / whitespace-only / reordering hunks. Every hunk traces to a plan scenario or contract (config field, position-signal swap + pure helper, argv-shape + candidate threading, resolver extension).

## Definition of Done
- [x] All plan scenarios implemented and tested
- [x] Interaction scenarios have concurrent-state tests
- [x] Stack expectations respected; stack-spec tests pass
- [x] Product Contract honored; Acceptance checks pass; no silent behavior change
- [x] Pipeline green — pytest 1332 passed / 40 skipped; ruff check + format clean; mypy clean except the pre-existing `code_scalpel/tools/files.py:8` (not in this diff; acknowledged in CLAUDE.md)
- [x] State file updated (`.ai-pm/state/current.md`)
- [x] Product Impact Report present (when contract touched) — contract `## Built/changed by` + state file carry the impact; reuses existing contract, no new behavior beyond the documented Must-work
- [x] Docs updates landed
- [x] Expected artifacts exist (plan, this review, contract — contract is the reused `run-plan.md`)
- [n/a] Product-readiness gate resolved — feature is non-user-facing (every scenario subject is the system / deliverable / gate, no human-role subject); state file records the gate EXEMPT. Wider-reach product/security implications routed through the threat-model update. See note 1.
- [n/a] Validation gate — software-kind project
- [x] Failure-inventory negative-space tests present — S9 + S10 each have tests

**DoD: pass**

## Blocking

(none)

## Notes (product)

1. The feature was classified non-user-facing (advocate gate EXEMPT), so no
   `flat-layout-run-smoke_advocate.md` was produced — its scenarios are all
   system/deliverable/gate-subject. The two sibling features in this family
   (`acceptance-spec-in-tasks`, `acceptance-self-fix-loop`) DID get advocate
   artifacts, and this change widens where LLM-produced code actually runs.
   The exemption is defensible by the scenario-subject rule and the security
   dimension was instead handled via the threat-model update — but if the PM
   considers "run my deliverable on more layouts / earlier" a user-visible
   trade-off worth an advocate pass, that is a product call, not a code fix.
   Why it matters: the exemption is correct by the mechanical rule, but the PM
   may want to confirm the autonomy-reach change needed no foundational-gap pass.

2. The plan's Test-plan named an interaction test
   `test_recovered_cli_committed_once_with_later_tasks`; the underlying property
   (recovered task committed exactly once, later tasks proceed) is covered by
   `test_self_fix_fires_at_last_applicable` + the unchanged feature-3
   `test_recovered_task_is_committed`, but not by a single test of that name.
   Coverage is complete; only the named-test granularity differs.
   Why it matters: no behavior gap — purely a naming/granularity observation
   so the PM is aware the plan's test list and the landed tests differ in shape.

## Verdict
approve

## Code review findings

Pass-2: code-review (built-in) on **Sonnet** (`review-diff-model: auto`, self-reported `claude-sonnet-4-6`) + seam-completeness on the session model. Semgrep skipped (not installed). Backlog dedup: no overlap (the flat-layout backlog item is *this* feature, now landed).

Seam check: (a) exception-boundary **clean** (single `resolve_pkg` caller, `ValueError` caught at the same `plan_verify` boundary, tomllib errors wrapped); (b) store-contract **clean** for the descriptor consumer (`_argv_prefix` handles both kinds) — but see CR1 re the config field; (c) one finding (= CR5). `_last_applicable_index` confirmed correct by BOTH reviewers: -1 sentinel on empty/all-done/no-applicable/raising-predicate, `should_run_now` never True at a wrong position, strictly more conservative than the old index, verify_task + self-fix helpers untouched.

Five findings — all directed to pm-coder (security-bearing run-execution path this feature *widens*):

- **CR1 — FIX — the new `run_smoke_script_candidates` config knob is inert in production** (`python_cli_adapter.py:82-86` / `skills/__init__.py:106` / `plan_verify.py:165`). The registry singleton is built at import time with the `AgentConfig()` default; `acceptance_adapter(root)` → `bind(root)` carries that import-time default, and `plan_verify` calls `acceptance_adapter(agent._cwd)` without the live `agent._config`. A user-set candidate list has no effect, and the line-82 comment claiming it is threaded is false. **Orchestrator-verified** (code-review correct; the seam (b) "live value flows" conclusion missed the import-time singleton). Fix: thread the live `AgentConfig.run_smoke_script_candidates` to the resolver (e.g. `acceptance_adapter(root, config)` → bind with the live list), and correct the comment.

- **CR2 — FIX — `_single_root_package` can return `'src'` as a module** (`python_pkg.py:160`). If `src/` itself carries `__init__.py` + `__main__.py` (a confused scaffold), rung 3 returns `'src'` → `python -m src` (wrong/failing run) before rung 4 inspects `src/<pkg>`. Wrong-runnable on the widened run-smoke surface. Fix: exclude reserved dir names (`src`, `tests`, `docs`) from the root-package scan.

- **CR3 — FIX — `_single_root_script` accepts path-traversal candidates** (`python_pkg.py:196`). A config candidate like `../evil.py` resolves outside the project root and would execute as `python ../evil.py` — violates the project's "stay inside the project root" architectural constraint (bwrap mitigates but does not eliminate). Fix: reject any candidate that is not a simple filename (`Path(name).name == name`, no `/`, no `..`) — ideally a pydantic validator on the config field so it's rejected at load time.

- **CR5 / seam(c) — FIX — `_single_src_package` ambiguity is asymmetric** (`python_pkg.py:180-193`). Every other rung raises on ambiguity, but the src rung silently picks the single `__main__.py`-runnable package among multiple candidates (or falls through), so a stray `__main__.py` in a sibling src package silently runs the wrong package. Flagged by BOTH reviewers. Fix: make it symmetric — raise on genuine multi-package ambiguity, auto-pick only when the runnable package is unique.

- **CR4 — FIX (cheap) — contradictory `_from_pyproject` docstring** (`python_pkg.py:97`). The docstring says ambiguity returns `None` "only when…" but the code always raises on a declared-but-ambiguous rung. Fix the wording to match (ambiguity raises; the try/except only swallows TOML/IO errors).

### Fixes directed to pm-coder
CR1, CR2, CR3, CR4, CR5. After they land, re-verify and stamp.

## Code review: 2026-06-07 — passed

Reviewers: code-review (built-in) on Sonnet + seam-completeness on the session model. Five findings (CR1–CR5), all FIX, landed in `424f6f0`. Re-verified on Sonnet: all five CONFIRMED fixed, no new bugs, new-seam check clean (every `bind` override compatible with the optional `script_candidates`; no circular import; all `acceptance_adapter` callers intact). Pipeline green: pytest 1350 passed / 40 skipped (+18 tests), ruff check + format clean, mypy clean except the pre-existing `tools/files.py:8`.
