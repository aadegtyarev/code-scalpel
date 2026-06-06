# Execution state

Single source of truth for the currently active task. Overwritten as the task progresses; archived to `.ai-pm/state/archive/<topic>-<YYYY-MM-DD>.md` on completion.

PM reads this when curious about progress; PM never edits it. Agents read it as their first step and update it as their last step.

---

## Task

Capture the TUI UX/ergonomics as an authoritative spec in docs/ui-guide.md (migration step 0, feat/capture-tui-ux-spec) — de-risks later TUI rewrite / seam evolution. Backend redesign (feature 1: project-adapter-abstraction) is PARKED behind this.

## Status

documenting (TUI UX spec capture)

## Done

- Bootstrap: legacy adoption (full documentation mode) completed.
- Spike: diagnosed "doesn't work as a product" — 19% task_solved across 107 probe runs; root cause = no acceptance/run gate in Definition-of-Done (only 2% of failed runs ever invoked the deliverable). Language-agnostic.
- pm-architect arch note written: `.ai-pm/arch/backend-redesign_arch.md` (project-adapter abstraction + acceptance gate in run_plan; TUI UX preserved, impl/seam evolvable under non-breakage discipline).

## Remaining

- PM picks first feature to plan from the migration path.
- Open PM decisions: 3/3-gate as DoD vs manual release check; Fork-2 acceptance-spec source; agent.py decomposition scope.

## Touched files

- .ai-pm/arch/backend-redesign_arch.md (new)
- docs/* + .ai-pm/* from bootstrap (committed on branch chore/bootstrap-ai-pm, PR #166)

## Next step

PM selects first feature (recommended: feat/project-adapter-abstraction) → run `/pm-plan`.

## Validation

pending (per-feature)

## Notes

Project adopted the protocol over an existing mature codebase (v0.12.5.dev0, v0.14 open in docs/plan.md §31). docs/plan.md remains the long-range design narrative.

---

## How to use this file

- **Agent step 1** — read this file before doing anything else. If it says "done", do not start work without explicit PM instruction to start a new task.
- **Agent step last** — overwrite this file with the new state before stopping.
- **Session restart** — re-read this file. It should be enough to continue without scrolling chat history.
- **Task complete** — copy this file to `.ai-pm/state/archive/<topic>-<YYYY-MM-DD>.md` and reset this one to a new task or to "Status: idle".
