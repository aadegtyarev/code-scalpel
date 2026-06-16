# Product Contract: Code mode — one supervised patch step

## User value

A developer can hand the agent one concrete, small task ("fix the crash
when the query is empty", "add a flag") and get a single reviewable change:
the agent reads what it needs, proposes a file write shown as a diff, and —
once applied — runs the tests. Small, inspectable, reversible.

## Who uses it

A developer making a focused change to their own code through a weak local
model, who wants to see and approve each edit.

## Must work

- The agent reads only the files it needs, then proposes a `write_file`
  change rendered as a diff card.
- At skeptic trust the user gets an explicit apply / reject / regenerate
  gate before anything lands.
- After apply, tests run automatically and the result is shown.
- On a failed test the agent runs a debug pass and offers a retry with a
  fix hint.

## Must not break

- At skeptic trust, no patch is applied without user confirmation.
- A failed change leaves partial progress on disk for inspection — it is
  not silently discarded.
- The retry loop is bounded (anti-loop caps) and cannot spin forever.
- Trust levels and the apply gate — see `docs/architecture.md`
  `## Behavioral contract`.

## Acceptance checks

- `code_with_retry` unit tests — verify propose → apply → test → retry.
- Patch/edit-block and `write_file` mode tests — verify writes are correct.
- Policy tests — verify skeptic requires confirm, hard-blocks refuse.

## Out of scope

- Multi-task autonomous execution (that is `/go`).
- Editing existing tests on the user's behalf.

## Last reviewed

2026-06-06 — verified against tree at doc bootstrap.

## Built/changed by

- (legacy — pre-protocol; v0.1–v0.9)
