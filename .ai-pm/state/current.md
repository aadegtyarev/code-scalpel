# Execution state

Single source of truth for the currently active task. Overwritten as the task progresses; archived to `.ai-pm/state/archive/<topic>-<YYYY-MM-DD>.md` on completion.

PM reads this when curious about progress; PM never edits it. Agents read it as their first step and update it as their last step.

---

## Task

(none — project just initialized under ai-pm-protocol)

## Status

idle

## Done

- Bootstrap: legacy adoption (full documentation mode) completed.

## Remaining

- Await first feature description from PM.

## Touched files

(none active)

## Next step

PM describes a feature → run `/pm-plan`.

## Validation

pending

## Notes

Project adopted the protocol over an existing mature codebase (v0.12.5.dev0, v0.14 open in docs/plan.md §31). docs/plan.md remains the long-range design narrative.

---

## How to use this file

- **Agent step 1** — read this file before doing anything else. If it says "done", do not start work without explicit PM instruction to start a new task.
- **Agent step last** — overwrite this file with the new state before stopping.
- **Session restart** — re-read this file. It should be enough to continue without scrolling chat history.
- **Task complete** — copy this file to `.ai-pm/state/archive/<topic>-<YYYY-MM-DD>.md` and reset this one to a new task or to "Status: idle".
