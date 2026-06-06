# Execution state

Single source of truth for the currently active task. Overwritten as the task progresses; archived to `.ai-pm/state/archive/<topic>-<YYYY-MM-DD>.md` on completion.

PM reads this when curious about progress; PM never edits it. Agents read it as their first step and update it as their last step.

---

## Status

idle

Last shipped: `feat/acceptance-self-fix-loop` (feature 3 of the backend redesign) —
bounded, trust-gated acceptance self-fix loop. Archived to
`.ai-pm/state/archive/acceptance-self-fix-loop-2026-06-07.md`. PR open / awaiting
PM merge.

Next candidate (per the backend-redesign roadmap): feature 5 — node-cli-adapter.

---

## How to use this file

- **Agent step 1** — read this file before doing anything else. If it says "done", do not start work without explicit PM instruction to start a new task.
- **Agent step last** — overwrite this file with the new state before stopping.
- **Session restart** — re-read this file. It should be enough to continue without scrolling chat history.
- **Task complete** — copy this file to `.ai-pm/state/archive/<topic>-<YYYY-MM-DD>.md` and reset this one to a new task or to "Status: idle".
