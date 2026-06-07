# Execution state

Single source of truth for the currently active task. Overwritten as the task progresses; archived to `.ai-pm/state/archive/<topic>-<YYYY-MM-DD>.md` on completion.

PM reads this when curious about progress; PM never edits it. Agents read it as their first step and update it as their last step.

---

## Status

idle

Last shipped: `feat/flat-layout-run-smoke` — flat-layout run-smoke resolution +
last-applicable enforcement. Archived to
`.ai-pm/state/archive/flat-layout-run-smoke-2026-06-07.md`. PR opened + merged (PM).

In flight (not a coding task): deep-research on weak-14B agent configuration
(temperature/edit-format/context/syntax-recovery) — launched, results pending. The
Step-5.5 measurement showed the feature works but score is flat due to downstream
settings/harness bugs (f-string thrashing at retry temp 0.1; spec↔deliverable name
mismatch). Next concrete step depends on the research outcome.

---

## How to use this file

- **Agent step 1** — read this file before doing anything else. If it says "done", do not start work without explicit PM instruction to start a new task.
- **Agent step last** — overwrite this file with the new state before stopping.
- **Session restart** — re-read this file. It should be enough to continue without scrolling chat history.
- **Task complete** — copy this file to `.ai-pm/state/archive/<topic>-<YYYY-MM-DD>.md` and reset this one to a new task or to "Status: idle".
