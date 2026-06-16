# Product Contract: Debug mode — failure investigation

## User value

When something is broken, the developer can ask the agent to investigate
rather than blindly patch: it forms a hypothesis, gathers evidence (it can
run small Python snippets to test ideas without writing files), and
proposes a fix. A compact fix hint replaces raw traceback dumps.

## Who uses it

A developer staring at a failing test or traceback who wants a
hypothesis-driven diagnosis on a weak local model.

## Must work

- The user switches to debug mode and describes the failure; the agent
  produces a hypothesis, evidence, and a suggested fix.
- The agent can run Python to check hypotheses without mutating files.
- An automatic debug pass also fires on a failed test during `code`/`/go`,
  feeding the builder a compact fix hint.

## Must not break

- The debug pass cannot write files (investigate, don't mutate).
- The debug loop is bounded (max attempts, hypothesis/test-output equality
  stops) — it cannot thrash forever.
- See `docs/architecture.md` `## Behavioral contract`.

## Acceptance checks

- `debug_pass` tests — verify structured output, write_file exclusion, and
  the anti-loop caps.

## Out of scope

- Applying the fix automatically without going through the code/patch gate.

## Last reviewed

2026-06-06 — verified against tree at doc bootstrap.

## Built/changed by

- (legacy — pre-protocol; v0.12)
