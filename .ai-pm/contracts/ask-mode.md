# Product Contract: Ask mode — conversational code Q&A (needs PM validation)

## User value

A developer can ask questions about their codebase in plain language and
get grounded answers without the agent touching any files. It uses the
project map, search, and remembered notes to answer "where is X used?",
"how should I add Y?", "explain this module" — cheaply, on a weak local
model.

## Who uses it

A developer exploring or reasoning about their own repository before
making changes.

## Must work

- The user can type a question and get an answer that cites real code
  (`path:symbol`) rather than inventing methods.
- The agent reads only the project map / search results, not whole files,
  unless reading is required to answer.
- Relevant stored notes are recalled automatically when they match the
  question.
- The agent offers to switch to plan/code when the user signals intent to
  build.

## Must not break

- Ask mode never modifies code or files.
- The agent must not fabricate a symbol/method that does not exist (the
  read-before-show guard must hold).
- Mode taxonomy and grounding behavior — see `docs/architecture.md`
  `## Behavioral contract`.

## Acceptance checks

- LLM bench grounding cases (admit-missing-method, reads-file-first,
  cite-file-when-pointing, do-not-invent-AgentState-method) — verify
  no-fabrication.
- TUI tests for slash/mode handling — verify ask mode stays read-only.

## Out of scope

- Applying changes, running the plan, or writing patches (that is code/go).

## Last reviewed

2026-06-06 — extracted from legacy code — needs PM validation

## Built/changed by

- (legacy — pre-protocol; v0.1–v0.3)
