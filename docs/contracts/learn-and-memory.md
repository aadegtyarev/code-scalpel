# Product Contract: Project memory & learned recipes

## User value

The developer can teach the agent once and have it remember: `/remember`
stores a project fact that is automatically recalled on relevant future
turns, and `/learn` captures a technology's conventions (from the model's
knowledge or a documentation URL) as a reusable recipe/skill file. The
agent stops re-asking what it has already been told.

## Who uses it

A developer who wants the agent to retain project preferences and stack
knowledge across sessions.

## Must work

- `/remember <fact>` stores a note; relevant notes are auto-recalled on
  future turns that match.
- `/recall [query]` browses or searches stored notes.
- `/learn <name> [--url] [--type recipe|skill]` writes a recipe/skill
  markdown file and shows a hint about how it loads.
- Recipes load eagerly (every turn) or lazily (only when the task mentions
  a keyword), defaulting to lazy.

## Must not break

- Notes are size-capped so they cannot bloat every turn's context.
- Recipe discovery priority is project → user → bundled.
- Memory and recipes persist across sessions (survive `/new` — `[?]`
  confirm: `/new` wipes session/state, memory.db is separate).
- Loading semantics and discovery order — see `docs/architecture.md`
  `## Behavioral contract`.

## Acceptance checks

- `memory.py` tests (add/search/all/delete/clear, size cap, FTS5 ranking).
- `recipes.py` / `learn.py` tests (eager/lazy parsing, keyword match,
  discovery priority, `load: lazy` default in the learn prompt).

## Out of scope

- Semantic/vector retrieval (FTS5/BM25 only today).
- Contradiction detection / dedup across notes.

## Last reviewed

2026-06-06 — verified against tree at doc bootstrap.

## Built/changed by

- (legacy — pre-protocol; v0.3, v0.6)
