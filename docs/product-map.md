# Product map — what the system does, by contract

> Status: **live** — contract is in force · **deprecated** — superseded, kept for history.

> Note: code-scalpel adopted the protocol over an existing mature codebase. The 8 contracts below were reconstructed from the code at doc bootstrap (verified against tree). Long-range design narrative: `plan.md` §31.

## Agent modes (interactive)

### [ask-mode](contracts/ask-mode.md) — live

- **User value:** A developer asks questions about their codebase in plain language and gets grounded answers (citing real `path:symbol`) without the agent touching any files.
- **Out of scope:** applying changes, running the plan, or writing patches.

Built by: — pre-protocol (reconstructed at bootstrap; no feature plan/review yet)

### [code-mode](contracts/code-mode.md) — live

- **User value:** A developer hands the agent one small task and gets a single reviewable change — read what's needed, propose a diff, run the tests once applied. Small, inspectable, reversible.
- **Out of scope:** multi-task autonomous execution (`/go`); editing the user's existing tests.

Built by: — pre-protocol (reconstructed at bootstrap; no feature plan/review yet)

### [debug-mode](contracts/debug-mode.md) — live

- **User value:** When something breaks, the agent investigates hypothesis-first (running small snippets to test ideas) and proposes a fix instead of blindly patching.
- **Out of scope:** applying the fix automatically without going through the code/patch gate.

Built by: — pre-protocol (reconstructed at bootstrap; no feature plan/review yet)

### [plan-mode](contracts/plan-mode.md) — live

- **User value:** For a goal bigger than one edit, the agent turns it into an ordered, editable task list — annotated with needed skills and surfacing architectural decision points up front, before any code is written.
- **Out of scope:** executing the tasks (`/go`); resolving forks.

Built by: — pre-protocol (reconstructed at bootstrap; no feature plan/review yet)

### [review-mode](contracts/review-mode.md) — live

- **User value:** A developer points the agent at a file or diff and gets a structured critique (summary, tagged issues with file:line, suggestions) without the agent changing anything.
- **Out of scope:** applying any suggested fix (switch to code mode).

Built by: — pre-protocol (reconstructed at bootstrap; no feature plan/review yet)

## Autonomous execution

### [run-plan](contracts/run-plan.md) — live

- **User value:** The developer lets the agent work through the task list on its own — each task read → write → test → commit — with stop conditions, optional per-step review, and an optional stronger upstream model to resolve hard decisions in a batch.
- **Out of scope:** auto-rewriting code from an override decision; per-task fork scoping.

Built by: — pre-protocol (reconstructed at bootstrap; no feature plan/review yet)

## Knowledge layer

### [learn-and-memory](contracts/learn-and-memory.md) — live

- **User value:** The developer teaches the agent once — `/remember` stores a project fact auto-recalled later; `/learn` captures a tool's conventions (model knowledge or a docs URL) as a reusable recipe. It stops re-asking what it was already told.
- **Out of scope:** semantic/vector retrieval (FTS5/BM25 only); contradiction detection across notes.

Built by: — pre-protocol (reconstructed at bootstrap; no feature plan/review yet)

## Setup & trust

### [setup-and-trust](contracts/setup-and-trust.md) — live

- **User value:** The developer gets from install to a working agent in one guided step (`code-scalpel init`), switches model profiles (local/fast/smart) without editing config, and dials autonomy up or down live with one trust knob.
- **Out of scope:** managing the LLM server itself; per-feature trust overrides beyond the three named levels.

Built by: — pre-protocol (reconstructed at bootstrap; no feature plan/review yet)

## Infrastructure (no user-facing contract)

_None yet — backend/infra features will appear here as they are planned through the protocol._
