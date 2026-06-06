# Product Contract: Review mode — structured code review (needs PM validation)

## User value

The developer can point the agent at a file or a diff and get a structured
critique — a short summary, tagged issues with file:line locations, and
suggestions — without the agent changing anything.

## Who uses it

A developer who wants a second opinion on code or a pending change before
committing.

## Must work

- The user points review mode at a file or diff; the agent reads the actual
  code first.
- Output is structured: Summary, Issues tagged `[bug]/[risk]/[design]/[nit]`
  with file:line, and Suggestions.

## Must not break

- Review mode never modifies code and must not emit patch/SEARCH-REPLACE
  output.
- Findings cite real lines (the agent reads the file before pointing).
- Issue tag taxonomy — see `docs/architecture.md` `## Behavioral contract`.

## Acceptance checks

- Review-mode prompt/addendum tests — verify the structured format and the
  no-patch constraint.

## Out of scope

- Applying any suggested fix (switch to code mode for that).

## Last reviewed

2026-06-06 — extracted from legacy code — needs PM validation

## Built/changed by

- (legacy — pre-protocol; v0.6)
