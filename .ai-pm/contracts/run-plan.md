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
  (`python -m <pkg> --help` for a python-cli project) and **records +
  surfaces** the verdict (`passed`/`failed`/`noop`) — so the user can see
  whether the deliverable actually ran, not just whether tests passed.
- `/escalate` (or end of `/go`) flushes pending forks through the upstream
  model and surfaces disagreements as overrides.

## Must not break

- A task is `done` only if its tests pass and git HEAD advanced; otherwise
  it is `failed`. (The acceptance run-smoke is **recorded, not enforced** —
  it never demotes a task in this iteration; enforcement, gated by a
  CLI-vs-library signal, lands with `feat/acceptance-spec-in-tasks`.)
- The acceptance run-smoke **must not break any existing `/go` flow** — it
  is observational for every project type, so no task that was `done`
  before is failed by it (incl. python libraries with no CLI entrypoint).
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
- Acceptance run-smoke plumbing — verdict recorded/persisted/surfaced,
  never demotes (`test_acceptance_records_failed_but_does_NOT_demote*`,
  `test_acceptance_library_project_not_demoted`).
- Outcome probe (`notes_cli`, N≥3, task_solved verdict) — the release-gate
  integration check; gains teeth in `feat/acceptance-spec-in-tasks`
  (feature 4) when the acceptance gate becomes enforcing.

## Out of scope

- Auto-rewriting code from an override decision.
- Per-task fork scoping (all later tasks assumed to depend on a fork).
- **Enforcing** the acceptance gate (demote on run-smoke failure) — needs
  the CLI-vs-library signal; deferred to `feat/acceptance-spec-in-tasks`.

## Last reviewed

2026-06-06 — extracted from legacy code — needs PM validation

## Built/changed by

- (legacy — pre-protocol; v0.7–v0.14)
- [acceptance-gate-run-plan](../../docs/features/acceptance-gate-run-plan_plan.md) — run-smoke plumbing + observability (recorded, not enforced)
