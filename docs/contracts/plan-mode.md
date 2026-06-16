# Product Contract: Plan mode — build a task list

## User value

For a task bigger than one edit, the developer can have the agent turn a
goal into an ordered, editable task list before any code is written. The
plan is annotated with the skills each task needs and surfaces
architectural decision points up front, so the developer reviews the
approach before execution.

## Who uses it

A developer scoping a multi-step change who wants to see and adjust the
plan before the agent acts.

## Must work

- The agent turns a goal into a task list saved to `TASKS.json` / `TASKS.md`
  and asks clarifying questions.
- Each task is auto-annotated with the skills it needs, visible and
  editable in the file.
- Architectural forks in the plan can be detected and surfaced before any
  code (opt-in).
- The user can edit, re-annotate (`/annotate`), or hand the plan to `/go`.

## Must not break

- Plan mode never executes code.
- The task file is the source of truth and is written atomically.
- Status / task taxonomy — see `docs/architecture.md` `## Behavioral
  contract`.

## Acceptance checks

- `plan.py` parse/render tests (`TASKS.json` ↔ `TASKS.md`).
- `annotate_plan` / skill-annotation tests.
- `detect_forks` tests — verify degenerate single-option forks are dropped.

## Out of scope

- Executing the tasks (that is `/go`).
- Resolving forks (that is the fork-delegation feature).

## Last reviewed

2026-06-06 — verified against tree at doc bootstrap.

## Built/changed by

- (legacy — pre-protocol; v0.3, v0.7, v0.11)
