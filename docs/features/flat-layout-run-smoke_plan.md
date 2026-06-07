# Flat-layout run-smoke + deliverable-complete enforcement — plan

Source: PM-requested ("делай" after the Step-5.5 finding that the self-fix loop is
inert on the canonical scenario); PM chose scope A+B (close both gaps in one feature).

## Why (one paragraph)

The acceptance gate and the just-shipped self-fix loop are **inert on the canonical
scenario** (a weak local model building a notes-style CLI). Two gaps block them, both
confirmed live: (A) run-smoke only resolves `src/`-layout or hatchling projects, so the
flat-layout projects weak models actually build return `skipped (pkg-unresolvable)` —
no run ever happens; and (B) enforcement fires only at the *last* plan task, which the
model almost always makes a test task, so the gate lands on a non-applicable task and
never verifies the CLI built earlier. Baseline probe (current `main`, N=5): deliverables
score ~7/8 mechanically but `/go` gives up early (`max_failures`) — exactly the zone a
working self-fix would close. This feature makes run-smoke run on the layouts the
model builds (A) and enforces the runnable CLI at the last *applicable* task (B), so the
gate + self-fix finally engage. Arch decisions: `.ai-pm/arch/flat-layout-run-smoke_arch.md`.

## Scenarios

1. **Flat-layout root package runs.** A project with a root-level package dir containing
   `__main__.py` (no `src/`, no hatchling target) — run-smoke resolves it and runs
   `python -m <pkg> <args>` instead of returning `pkg-unresolvable`.
2. **Flat-layout root script runs.** A project whose entry is a single root-level script
   (`cli.py` / `main.py` / `__main__.py`, config-owned candidate list) — run-smoke runs
   `python <script> <args>`.
3. **Console-script entry point runs.** A project declaring a single `[project.scripts]`
   console entry in `pyproject.toml` — run-smoke resolves it (declared outranks discovered).
4. **src-layout / hatchling unchanged.** An existing `src/<pkg>` or hatchling-wheel-target
   project resolves exactly as today (no regression).
5. **Ambiguity still raises.** Multiple equally-ranked candidates at the same precedence
   rung (e.g. two root scripts, two root packages) → resolve raises → `pkg-unresolvable`,
   never a guessed run.
6. **Deliverable-complete enforcement.** When the runnable CLI is built by an earlier task
   and the final plan task is non-CLI (tests/docs), the gate enforces the CLI at the **last
   applicable task** (the last task whose derived spec is applicable) — so a failing CLI
   run-smoke demotes `done → failed` and the self-fix loop engages, at `optimist`/`yolo`.
7. **Early task still never demoted (no-regression).** An early/intermediate task of a
   CLI-intent plan — before the CLI is the last applicable task — is *observed*, never
   demoted; the greenfield "skeleton fails because the CLI isn't wired yet" false-demote
   does not return.
8. **Library / no-applicable-spec still never failed (no-regression).** A plan with no
   applicable acceptance spec (a library, a non-CLI project) has no last-applicable index
   → never enforced → keeps the observational behavior.

### Failure paths (external I/O — file system; from the failure-inventory check)
9. **Unreadable / malformed `pyproject.toml`** during resolution → treated as "no declared
   target" (fall through to filesystem discovery), never a crash — matches today's
   `_from_pyproject` tolerance.
10. **No resolvable runnable at any rung** (absence) → resolve raises `ValueError` →
    `pkg-unresolvable` (unchanged contract); an applicable spec still records the demotion,
    a library still observes.

## Existing behaviors this feature touches
(from `docs/user-journeys.md` Journey 5 / `.ai-pm/contracts/run-plan.md`)
- The acceptance gate's three-signal rule (intent × position × state) — **position** changes
  from "last not-done task" to "last *applicable* task". Must not break the two load-bearing
  no-regression invariants below.
- "An early task of a CLI-intent plan is NEVER demoted by the acceptance check."
- "Library / no-applicable-spec NEVER failed" (the load-bearing no-regression invariant).
- The self-fix loop (feature 3) — unchanged in mechanism; only *which* task triggers it
  changes (Q2 keeps `verify_task` + all self-fix helpers untouched).
- Status taxonomy unchanged — reuse `done → failed`; no new status.

## Contracts
- `resolve_pkg(root) → RunTarget` (was `→ str`). Returns a typed descriptor carrying the
  argv shape: `kind ∈ {module, script}` + `target` (the `-m` package name, or the script
  path). `module` → `["python","-m",target,*args]`; `script` → `["python",target,*args]`.
  Ambiguity / absence → `ValueError` (unchanged). Precedence (declared outranks discovered):
  hatchling wheel target → single `[project.scripts]` console entry → root package with
  `__main__.py` → single `src/` package → single root entry script (config candidate list).
- Config (`config.py`, pydantic, no magic numbers): the root-entry-script candidate
  filename list (default `["__main__.py","main.py","cli.py"]`) — the only tunable.
- `_last_applicable_index(tasks)` replaces the position source for `should_run_now`
  (computed from the existing pure `acceptance_applicable(task)` predicate — no LLM, no I/O).

## Stack expectations touched
(from `docs/stack-notes.md`)
- **Python packaging / hatchling + `[project.scripts]`**: "Entry point `code_scalpel.cli:app`
  (`pyproject.toml` `[project.scripts]`)" — resolution must read declared entry points
  before guessing from the filesystem, and respect the src-layout/hatchling forms already
  supported. Source: https://hatch.pypa.io/latest/ · https://packaging.python.org/en/latest/specifications/entry-points/
- **Pydantic v2 (config)**: the candidate-script list is a typed `AgentConfig` field with a
  literal default — no magic numbers in the resolver. Source: https://docs.pydantic.dev/latest/

## Interaction scenarios
(not provably isolated — shares the run-loop, the acceptance verdict path, and the self-fix
loop's per-task trigger)
- When the **last applicable task ≠ the last not-done task** (CLI built early, tests last):
  the gate now enforces at the CLI task; verify that subsequent test/doc tasks run *after*
  it are NOT re-enforced and do not re-trigger self-fix.
- When **self-fix recovers the CLI at the last-applicable position** while later non-CLI
  tasks remain: the recovered task is committed once, later tasks proceed normally, and the
  run's stop/streak logic is unchanged.
- When a **flat-layout run-smoke fails and self-fix rebuilds**: the per-attempt HEAD
  re-snapshot + identical-output break + budget (feature 3) still bound the loop — the
  wider run-smoke reach does not change the self-fix bounds.

## Test plan
- Existing tests that must pass: **all** — especially `test_python_cli_adapter.py`,
  `test_acceptance_enforcement.py`, `test_acceptance_gate.py`, `test_acceptance_self_fix.py`.
- New tests (resolution — Gap A):
  - `test_resolve_root_package_with_main`: root pkg + `__main__.py` → `(module, <pkg>)`.
  - `test_resolve_root_script`: single root `cli.py` (no pkg) → `(script, "cli.py")`.
  - `test_resolve_project_scripts_entry`: single `[project.scripts]` entry → resolved,
    declared outranks a sibling root script.
  - `test_resolve_src_layout_unchanged`: `src/<pkg>` → `(module,<pkg>)` (regression).
  - `test_resolve_hatchling_target_unchanged`: hatchling wheel target → resolved (regression).
  - `test_resolve_ambiguous_root_scripts_raises`: two root scripts, no declared entry →
    `ValueError` (never guess).
  - `test_resolve_absence_raises`: empty/library project → `ValueError` → pkg-unresolvable.
- New tests (argv shape — adapter):
  - `test_run_smoke_module_argv`: `module` kind → `["python","-m",pkg,*args]`.
  - `test_run_smoke_script_argv`: `script` kind → `["python",script,*args]`.
- New tests (enforcement position — Gap B):
  - `test_enforce_at_last_applicable_not_last_task`: plan = [CLI task, test task]; CLI
    run-smoke fails → CLI task demoted `done → failed` (given/when/then: applicable CLI is
    not the last task, yet it is enforced).
  - `test_self_fix_fires_at_last_applicable`: same shape at `optimist` → self-fix engages on
    the CLI task (production `run_plan` path — test-wiring-parity).
  - `test_early_cli_task_not_demoted`: plan with an early CLI-building task that is NOT the
    last applicable task → observed, never demoted (no-regression, scenario 7).
  - `test_library_plan_never_enforced`: no applicable spec anywhere → no enforcement (no-
    regression, scenario 8).
  - `test_last_applicable_equals_last_task_unchanged`: when the last task IS the applicable
    CLI (today's case) → behavior identical to current (regression).
- Failure-path tests (negative space):
  - `test_resolve_malformed_pyproject_falls_through`: unreadable/invalid `pyproject.toml` →
    filesystem discovery, no crash (scenario 9).
  - `test_resolve_no_runnable_raises_pkg_unresolvable`: absence → `ValueError` (scenario 10).
- Interaction-scenario tests:
  - `test_later_task_not_re_enforced_after_last_applicable`: last-applicable enforced, a
    later non-CLI task does not re-enforce / re-trigger self-fix.
  - `test_recovered_cli_committed_once_with_later_tasks`: self-fix recovers the CLI at the
    last-applicable position; exactly one commit for it; later tasks proceed.
- Stack-spec tests:
  - `test_declared_entry_outranks_discovered`: a `[project.scripts]` entry is chosen over a
    filesystem root script — verifies "declared outranks discovered" against the entry-points
    spec (URL in comment), not a self-consistent mapping.
- Verification (Step 5.5, not a unit test): re-run the `notes_cli` probe batch (N=5) and
  compare task_solved / mechanical score vs the recorded baseline (7/8, 7/8, 4/8, …) —
  the measurable before/after this whole feature exists for.

## Docs to update
- `docs/architecture.md`: `### Task outcome status` + `## State model` — the enforcement
  **position** is now the *last applicable* task (not the last task); add a decision record
  "Flat-layout run-smoke + deliverable-complete enforcement"; note the `resolve_pkg`
  descriptor change in the relevant section. (pm-architect.)
- `docs/threat-model.md`: **T05/T06/T10** reach update — run-smoke now executes LLM-produced
  code on MORE projects (wider reach/frequency, not a new trust boundary; bwrap stays the
  boundary; SC8/SC7 reaffirmed); bump `Last reviewed`. (pm-architect — required: security-
  bearing project, touches a `### Security-relevant surfaces` item.)
- `.ai-pm/contracts/run-plan.md`: change the position wording (last applicable task);
  **clear both `## Out of scope` reach-gap lines** (flat-layout run-smoke + the "fuller
  deliverable-complete signal"); update `## Must work` + `## Acceptance checks`. (orchestrator,
  at handoff.)
- `docs/plan.md`: mark this progress in the §31 roadmap. (pm-architect.)

## Out of scope
- **Non-python adapters** (node-cli-adapter is feature 5) — this feature is the python
  adapter only; the descriptor/precedence concept is python-specific here.
- **Multi-entry projects** beyond single-candidate-per-rung — ambiguity raises (scenario 5),
  a richer disambiguation UX is a separate concern.
- **Changing the self-fix loop mechanism** (budget / anti-loop / trust gate) — unchanged;
  only the trigger position moves.
- **A new task-outcome status** — reuses `done → failed`.
- Sibling categorical note — flat-layout *shapes* covered: root package (`__main__.py`),
  root script (candidate list), `[project.scripts]` entry, plus existing src/hatchling. Other
  exotic layouts (namespace packages, multiple top-level packages) → ambiguity→raise, a
  separate plan if ever needed.
