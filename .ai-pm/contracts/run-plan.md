# Product Contract: Run plan autonomously (`/go`) (needs PM validation)

## User value

The developer can let the agent work through the task list on its own —
each task read → written → tested → committed — with stop conditions that
keep it from running off the rails. Optional per-step review and
test-sanity checks raise quality; a stronger upstream model can resolve
hard decisions in batches. The developer gets a summary of what was done,
committed, and what still needs their attention.

## Who uses it

A developer who has a reviewed plan and wants supervised-autonomous
execution on a weak local model, controlling autonomy via the trust level.

## Must work

- `/go` lets the user pick scope (next task / full plan / manual retry).
- A git repo is ensured before the loop; each completed task is committed
  (auto-commit hook commits if the model forgot).
- Per-task: read → write → test → commit, with optional per-step review and
  test-sanity passes.
- At a fork, the trust level decides human vs auto resolution; the run
  summary reports tasks done/failed, commits, and pending upstream forks.
- For each completed task, the run-loop **runs the deliverable's run-smoke**
  and **records + surfaces** the verdict (`passed`/`failed`/`noop`) — so the
  user can see whether the deliverable actually ran, not just whether tests
  passed — AND **enforces** it (demote `done → failed`) **only when three
  signals agree**: the spec is *applicable* (intent — a derived spec judged
  from task text to be a runnable CLI deliverable), the task is the plan's
  **last applicable task** (position — the runnable CLI deliverable is enforced
  even when built before the final plan task, e.g. when the last task is
  tests/docs), and the run-smoke *fails* (state). Run-smoke resolves the
  runnable form deterministically — src-layout, hatchling, **and flat-layout**
  (root package, root entry script, or a `[project.scripts]` console entry);
  ambiguity/absence never guesses. The spec is a
  narrow-pass-derived, args-only `{applicable, args, expected}` (the adapter
  builds the argv; the model never emits a shell command) written back into
  the plan; a human-declared prose acceptance is a hint to the derivation,
  not an executed command.
- **When that final-step run-smoke fails at `optimist`/`yolo`**, the loop does
  not demote `done → failed` immediately — it re-feeds the failing run-smoke
  output to the model, rebuilds, and re-runs the smoke up to a bounded budget
  (`acceptance_self_fix_max_attempts`, default 3) before finally failing.
  Bounded by the budget **and** an identical-run-smoke-output anti-loop
  early-stop. At `skeptic` the task fails immediately and waits for the human
  (`policy.auto_confirm` gate). Self-fix fires only at the single
  last-applicable-task position; early CLI tasks and library / no-spec tasks
  are never self-fixed.
- `/escalate` (or end of `/go`) flushes pending forks through the upstream
  model and surfaces disagreements as overrides.

## Must not break

- A task is `done` only if its tests pass and git HEAD advanced; **and,
  where it is the last applicable task of a CLI-intent plan and an applicable
  acceptance spec exists, the deliverable's run-smoke passed** — otherwise it
  is `failed`. (Taxonomy unchanged; enforcement reuses the existing
  `done → failed` edge.)
- **An early task of a CLI-intent plan is NEVER demoted by the acceptance
  check** (case c). Only the **last applicable task** enforces — an
  intermediate task that builds toward the CLI, before the last applicable
  task, is *observed*, never failed by run-smoke. The greenfield
  "skeleton task fails because the CLI isn't wired yet" false-demote must not
  occur.
- The acceptance gate **must not break any `/go` flow that has no applicable
  acceptance spec** — the default-floor is never applicable, so python
  **libraries** with no CLI entrypoint (and any project type without a
  runnable deliverable) are **never wrongly failed**; they keep the
  observational behavior. This is the load-bearing no-regression invariant.
- The loop stops after N consecutive failures and keeps partial progress
  on disk (no silent discard).
- Editing `TASKS.md` mid-run is detected and stops the loop.
- Upstream overrides never auto-rewrite code — they are recorded for
  review.
- Status taxonomy, trust-driven fork resolution, stop reasons — see
  `docs/architecture.md` `## Behavioral contract` and `## State model`.

## Acceptance checks

- `run_plan` tests — task status transitions, stop reasons (max_failures,
  plan_modified, all_done, no_tasks), HEAD validation, auto-commit hook.
- Fork wiring / `UpstreamPendingQueue` / `flush_upstream` tests.
- Acceptance gate — demotes `done → failed` when intent × position × state
  all agree (applicable spec, last applicable task, failing run-smoke); never
  demotes an early (pre-last-applicable) task of a CLI plan, nor a not-applicable /
  floor / library task (no-regression).
- Flat-layout resolution (`tests/test_python_pkg.py`, `tests/test_flat_layout_run_smoke.py`)
  — `resolve_pkg → RunTarget(kind, target)` resolves root package / root entry
  script / `[project.scripts]` console entry as well as src-layout/hatchling;
  declared outranks discovered; ambiguity and absence raise (never guess).
- Last-applicable enforcement — the gate enforces the runnable CLI at the last
  applicable task even when a later plan task is non-CLI; early CLI tasks and
  library/no-spec plans are still never demoted.
- Outcome probe (`notes_cli`, **N≥3** to `task_solved`) — the **enforced
  release gate**. With flat-layout run-smoke + last-applicable enforcement
  landed, the gate now actually runs and enforces the CLI on the canonical
  scenario, so self-fix engages there. The gate's contract is therefore
  **"never false-fail; enforce the runnable CLI at the last applicable task;
  self-fix before demotion at optimist/yolo."**
- Self-fix loop (`tests/test_acceptance_self_fix.py`) — recovers a task when a
  rebuild fixes the run (`done`); exhausts the budget → `failed`; skeptic never
  auto-fixes; off-switch restores immediate `failed`; identical-output
  early-stop; language-agnostic (non-python adapter); HEAD re-snapshot per
  attempt; recovered task committed exactly once (S1–S7 + F8/F9).

## Out of scope

- Auto-rewriting code from an override decision.
- Per-task fork scoping (all later tasks assumed to depend on a fork).
- Non-python runnable adapters (a node-cli adapter and beyond) — the
  flat-layout resolution + last-applicable enforcement here are the python
  adapter; other languages are a separate plan.

## Last reviewed

2026-06-06 — extracted from legacy code — needs PM validation

## Built/changed by

- (legacy — pre-protocol; v0.7–v0.14)
- [acceptance-gate-run-plan](../../docs/features/acceptance-gate-run-plan_plan.md) — run-smoke plumbing + observability (recorded, not enforced)
- [acceptance-spec-in-tasks](../../docs/features/acceptance-spec-in-tasks_plan.md) — acceptance gate now enforces when intent × position × state agree (derived args-only spec + write-back; enforce at the plan's final step; early tasks + libraries never demoted); `notes_cli` 3/3 the live enforced release gate at the final step
- [acceptance-self-fix-loop](../../docs/features/acceptance-self-fix-loop_plan.md) — bounded, trust-gated self-fix loop: a failing final-step run-smoke at optimist/yolo is re-fed to the model and rebuilt up to a budget before `failed`; skeptic fails immediately; budget + identical-output break bound it; never self-fixes early CLI tasks or library / no-spec tasks
- [flat-layout-run-smoke](../../docs/features/flat-layout-run-smoke_plan.md) — closes the two reach gaps: flat-layout run-smoke resolution (`RunTarget(kind, target)` — root package / root script / `[project.scripts]`, declared outranks discovered, ambiguity→raise) + enforcement at the **last applicable task** (not the last plan task), so the gate + self-fix actually engage on the canonical scenario
