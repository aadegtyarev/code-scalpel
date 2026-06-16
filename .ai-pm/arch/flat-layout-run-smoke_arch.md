# Flat-layout run-smoke + deliverable-complete enforcement — design notes

## Context

The acceptance gate + the feature-3 self-fix loop are wired correctly but
**never engage on the canonical scenario** — a weak local model building a
notes-style CLI. Two independent gaps each break the chain, and together they
guarantee `notes_cli` is *observed*, never *enforced*, never *self-fixed*:

- **Gap A — `resolve_pkg` reach.** Weak models build **flat-layout** projects
  (package dir or entry script at repo root, or a `[project.scripts]` console
  entry). `resolve_pkg` resolves only a hatchling wheel target or a single
  `src/` package; everything else raises `ValueError` → `_run_smoke` records
  `failed`/`pkg-unresolvable`. Confirmed live: *every* run-smoke on the
  canonical plan returns `skipped (pkg-unresolvable)`. The gate cannot read a
  real run state because there is no real run.
- **Gap B — enforcement position.** `should_run_now = (idx == _last_not_done_index)`
  fires the gate on the **last not-done task** regardless of applicability. The
  14b coder builds the runnable CLI holistically in an early task and leaves a
  non-CLI final task (tests/docs). The gate lands on a task whose derived spec
  is **not applicable** → no demotion → self-fix (which attaches only to an
  acceptance demotion at the enforcing position) never fires.

Both are already named as follow-ups in `.ai-pm/contracts/run-plan.md`
`## Out of scope` ("flat-layout reach gap"; "a fuller deliverable-complete
signal"). This note resolves the two design questions; it is not an
implementation plan.

The load-bearing constraint shared by both: the existing no-regression
invariants in `## Must not break` MUST survive — **early CLI tasks never
demoted**, **libraries / no-applicable-spec never failed**, **status taxonomy
unchanged** (reuse `done → failed`), **deterministic (never guess)**, and the
self-fix loop's bounds (SC8: budget + identical-output break + trust gate)
intact.

## Adjacent implementations

1. **`resolve_pkg`** at `code_scalpel/skills/python_pkg.py` — the deterministic
   precedence ladder (hatchling target → single runnable `src/` pkg → single
   `src/` pkg), ambiguity/absence both `raise ValueError`. The shape the new
   flat cases extend; the "never guess" discipline they must inherit.
2. **`PythonCliAdapter.run_smoke`** at
   `code_scalpel/skills/python_cli_adapter.py` — today hardcodes
   `["python", "-m", pkg, *split_args]`. The single home of the python-specific
   argv prefix; it consumes `resolve_pkg`'s return. A root entry script needs a
   *different argv shape* (`["python", "<script>", *args]`), so the resolver
   must hand back enough to choose the shape, not just a name.
3. **`_last_not_done_index` / `should_run_now`** at
   `code_scalpel/plan_runner.py` — pure plan-structure position signal (no LLM,
   no I/O). Threaded into `verify_task(..., should_run_now=…)`; the only thing
   that flips an applicable spec from observe to enforce.
4. **`acceptance_applicable(task)`** at `python_cli_adapter.py:152` — a
   per-task, **pure** predicate (no `run_smoke`, no `resolve_pkg`, no LLM, no
   filesystem) that decodes the written-back derived marker and returns its
   `applicable` flag. Already the single source of the C→A precedence for the
   `pkg-unresolvable` path (`_adapter_applicable` in `plan_verify.py`). This is
   the lever for Gap B: "last *applicable* task" is computable as cheaply and
   deterministically as "last not-done task."

## Behavioral risks in this area

- **Gap A risk — a wrong `<pkg>`/shape silently false-demotes.** A guessed
  package or argv shape makes a healthy deliverable fail run-smoke → a real CLI
  task demoted. The mitigation is the existing rule: ambiguity → raise, not
  guess. New flat shapes widen the *match* surface, so each new shape must be
  an *unambiguous* signal of intent, and multiple competing shapes must raise.
- **Gap B risk — re-introducing the greenfield early-task false-demote.** The
  feature-2 "Timing fix" exists precisely because enforcing on a non-final
  early task false-demoted the skeleton ("CLI not wired yet"). Any move of the
  enforcement position must preserve "an early task of a CLI plan is never
  demoted by run-smoke."
- **Security surface widens (both gaps).** Gap A makes run-smoke *actually
  execute* on flat-layout projects it previously skipped — i.e. LLM-produced
  code runs on **more** projects. Gap B makes it execute at an **earlier**
  task position than the literal last task. Both stay on the existing
  model-output→shell boundary (T05/T06/T11/T12; SC1/SC2/SC3; bwrap the
  boundary), but the run-smoke *frequency and reach* go up — see "Threat-model
  / docs touch."

---

## Q1 — Flat-layout run-smoke resolution

**Decision needed:** which flat-layout shapes `resolve_pkg` supports, the
deterministic precedence across *all* shapes (existing + new), how the resolver
communicates the **argv shape** to the adapter, and what stays
ambiguity → raise.

### The shapes weak models actually produce

| # | Shape | Invocation | argv shape |
|---|---|---|---|
| S1 | hatchling wheel target in pyproject (**existing**) | `python -m <pkg>` | `-m` |
| S2 | single package under `src/` (**existing**) | `python -m <pkg>` | `-m` |
| S3 | package dir at **repo root** with `__main__.py` | `python -m <pkg>` | `-m` |
| S4 | `[project.scripts]` console-script entry in pyproject | `python -m <pkg>` (the entry's module) | `-m` |
| S5 | single root entry script (`cli.py` / `main.py` / `__main__.py`) | `python <script>` | `script` |

S1–S4 are all `python -m`; only S5 introduces a second argv shape.

### Option 1 — resolver returns a richer value (recommended)

Change `resolve_pkg` to return a small **deterministic descriptor** instead of
a bare `str` — the importable target *and* the argv shape — e.g. a frozen
2-field result `(kind: "module" | "script", target: str)` where `target` is the
package/module name for `module` and the script path for `script`. The adapter
builds the argv from the descriptor:

- `module` → `["python", "-m", target, *args]`
- `script` → `["python", target, *args]`

Precedence (first match wins, deterministic, top to bottom):

1. **hatchling wheel target** (S1) — the project's own ship declaration.
2. **`[project.scripts]`** single console entry (S4) — also a declaration; the
   entry's `module:func` target's module is the `-m` target.
3. **single root package with `__main__.py`** (S3).
4. **single `src/` runnable / single `src/` package** (S2) — existing rungs.
5. **single root entry script** from a fixed, ordered candidate set
   (`__main__.py`, `main.py`, `cli.py`) (S5) — lowest precedence because a bare
   script is the weakest declaration of intent.

Ambiguity → raise at every rung: >1 hatchling target, >1 `[project.scripts]`
entry, >1 root package with `__main__.py`, >1 candidate root script. Absence of
all → raise (today's behavior). The **declared** shapes (pyproject) outrank
**discovered** shapes (filesystem) so an explicit project statement always
wins over a heuristic.

- **Pros:** single deterministic source of both "what to run" and "how to run
  it"; the argv-shape decision lives next to the resolution that knows the
  shape (no second guess in the adapter); extends the existing ladder rather
  than forking it; "ambiguity → raise" generalizes cleanly to every new rung.
- **Cons:** changes `resolve_pkg`'s return type → touches `run_smoke`,
  `acceptance_spec._command`, and their tests (a typed-result migration, not a
  behavior change for S1/S2). Adds a config-owned candidate-script list (must
  live in `config.py`/pydantic, not a literal in the resolver — no magic
  list).

### Option 2 — resolver still returns `str`; adapter infers the shape

`resolve_pkg` returns the name; the adapter separately probes for a root
script. Rejected: splits the shape decision across two modules, re-introduces a
second filesystem read (drift risk between resolver and adapter), and the
adapter would have to re-derive "is this `-m` or a script?" — exactly the
guess the descriptor avoids. Also makes S5 (script) impossible to express as a
bare `str` without a sentinel convention, which is uglier than a typed field.

### Recommendation — Option 1

A typed descriptor `(kind, target)` returned by `resolve_pkg`, with the
declared-over-discovered precedence ladder above and ambiguity → raise at every
rung. It is the only option that keeps the "how to run it" decision
deterministic and single-homed, and it inherits the existing never-guess
contract verbatim. The candidate-script names and any ordering are config
tunables (no magic numbers / lists). Blast radius is the resolver + the two
adapter call sites (`run_smoke`, `_command`) + their tests; the verify/gate
path is untouched (it still consumes `spec.command`).

---

## Q2 — Deliverable-complete enforcement position

**Decision needed:** where enforcement lives so the runnable CLI deliverable is
enforced even when built before the final plan task, **without** re-introducing
early-task false-demotes, and how self-fix attaches.

### Option (a) — enforce at the LAST APPLICABLE task (recommended)

Replace the position signal: instead of `idx == _last_not_done_index`, compute
the **last not-done task whose derived spec is applicable** and enforce there.
`acceptance_applicable(task)` is already a pure, deterministic, per-task
predicate (decodes the written-back marker — no LLM, no I/O), so a new
`_last_applicable_index(tasks, adapter)` mirrors `_last_not_done_index`'s
structure and purity. `should_run_now = (idx == last_applicable_index)`.

- **Preserves "early task never demoted":** enforcement still fires at exactly
  **one** task position, and only on a task the derivation already judged a
  runnable-CLI deliverable. An early CLI-building task that is *not* the last
  applicable one is observed, never demoted — the greenfield skeleton case
  stays observational because it is not the last applicable task. A library /
  no-applicable-spec plan has **no** applicable task → `last_applicable_index`
  is `-1` → `should_run_now` is never True → never failed (the load-bearing
  no-regression invariant holds by construction — same as today, where the
  floor's `applicable=False` keeps it observational, now reinforced at the
  position layer too).
- **Self-fix attaches unchanged:** self-fix still attaches to a *task* (the
  last applicable one), through the existing `_acceptance_demoted` →
  `_self_fix_acceptance` path. Its bounds (SC8: budget, identical-output break,
  `policy.auto_confirm` trust gate, per-attempt HEAD re-snapshot) are untouched
  — only *which* task triggers it changes.
- **`should_run_now` / `_last_not_done_index` change:** `_last_not_done_index`
  stays (it remains a sensible fallback / may still inform other logic), but
  `should_run_now` is recomputed from a new `_last_applicable_index`. When the
  plan has no applicable task, the new index is `-1` and the gate degrades to
  today's observational behavior.
- **Blast radius — small.** One new pure helper in `plan_runner.py` + one line
  changing how `should_run_now` is derived. `verify_task` / `_verify_acceptance`
  are **unchanged** (they already take `should_run_now` as an opaque position
  signal). The feature-3 self-fix helpers are **unchanged**. The applicability
  read needs the bound adapter once at loop start (the run-loop already resolves
  `acceptance_adapter(agent._cwd)` in `plan_loading`/`verify`), computed once,
  pure, deterministic.

### Option (b) — a single END-OF-PLAN deliverable run-smoke

Drop per-task position entirely; after all tasks are attempted, run one
deliverable run-smoke decoupled from any task.

- **Preserves "early task never demoted":** trivially — no per-task enforcement
  at all.
- **Self-fix re-homing — large.** Self-fix today attaches to a *task* (rebuild
  via `code_with_retry` with the task prompt, re-verify, mark that task
  done/failed, commit once). An end-of-plan check has **no task** to attach a
  rebuild to: which task prompt does the self-fix re-feed? Which task's status
  flips? Who commits? This forces re-homing `_self_fix_acceptance` away from
  `_run_task` into a new post-loop stage, re-plumbing the budget/HEAD/commit
  bookkeeping, and inventing an end-of-plan outcome that is not a `TaskOutcome`.
- **Blast radius — large.** New post-loop stage, new outcome surfacing, self-fix
  re-home, and a second place that runs `verify_task`-like logic — risking
  drift with the per-task path. Higher chance of disturbing SC8's bounds.
- **Status taxonomy pressure:** an end-of-plan failure that is not a task
  failure tempts a new status / new edge — the contract forbids both.

### Option (c) — enforce at every applicable task

Rejected outright: re-introduces exactly the greenfield early-task
false-demote the feature-2 Timing fix removed (an early CLI task whose CLI
isn't wired yet would be enforced and fail). Violates "early task never
demoted."

### Recommendation — Option (a), last-applicable task

Smallest blast radius that *actually* makes self-fix fire on the canonical
plan. It is a one-predicate change to the position signal, reuses the existing
pure `acceptance_applicable` source, keeps `verify_task` and every feature-3
self-fix helper byte-for-byte the same, and preserves both no-regression locks
(early-task and library) **by construction**: enforcement fires at exactly one
position, and only when that position is an applicable-CLI deliverable. The
library/no-spec plan has no applicable index and degrades to today's
observational behavior. (b) buys generality the canonical scenario doesn't need
at the cost of re-homing the self-fix machinery and pressuring the taxonomy.

Note for the plan author: with (a), the run-loop reads per-task applicability
*before* the deliverable is built on a greenfield run — applicability is the
**derived marker written back pre-loop** (intent from task text), not a
build-state read, so `_last_applicable_index` is stable and correct on an empty
repo (same property the existing intent signal relies on). The plan should
confirm the pre-loop derivation populates the marker on all not-done tasks so
the index is computable at loop start.

---

## Must honor (no-regression + security + determinism)

From `.ai-pm/contracts/run-plan.md` `## Must not break`, the threat-model, and
the architectural constraints:

- **Early task of a CLI plan is NEVER demoted by the acceptance check** — the
  greenfield "skeleton fails because CLI isn't wired yet" false-demote must not
  return. (Q2 (a) holds this by construction: one enforcing position, applicable
  only.)
- **Library / no-applicable-spec NEVER failed** — no applicable index → never
  enforced; the default-floor stays `applicable=False`. (Both gaps preserve it.)
- **Status taxonomy unchanged** — reuse the existing `done → failed` edge; no
  new status, no new edge, no end-of-plan outcome type.
- **Deterministic — never guess.** Q1's new rungs each match an *unambiguous*
  intent signal; ambiguity → raise at every rung; declared (pyproject) outranks
  discovered (filesystem). Q2's position is pure plan structure + the pre-loop
  derived marker.
- **No magic numbers / lists** — the candidate-root-script names + ordering
  (Q1) live in `config.py`/pydantic, not as literals in the resolver.
- **Self-fix bounds intact (SC8)** — budget (`acceptance_self_fix_max_attempts`,
  default 3), byte-identical-output early stop, and the `policy.auto_confirm`
  trust gate (skeptic never auto-rebuilds) are untouched; Q2 (a) changes only
  *which* task triggers self-fix, not its mechanics. Per-attempt HEAD
  re-snapshot and exactly-once commit on recovery unchanged.
- **bwrap stays the execution boundary** — run-smoke continues to run through
  the trust-gated, `policy.py`-blocked, `bwrap`-sandboxed `execute()` path
  (SC1/SC2/SC3); args-only, adapter-owned argv (SC7) unchanged. No new trust
  boundary.

## Threat-model / docs touch (pointer — owned by pm-architect, not this note)

This feature **widens run-smoke reach** — LLM-produced code now actually
executes on flat-layout projects (Gap A) that previously skipped, and at an
earlier (last-applicable) task position (Gap B). No *new* boundary: it reuses
the existing model-output→shell path (SC1/SC2/SC3), code-owned verb +
args-only model input (SC7), and the self-fix bounds (SC8). The risk that
moves is **frequency/reach**, not kind. On landing, the doc-owner should:

- **`docs/threat-model.md`** — update **T05** and **T06** (autonomous loop now
  executes the deliverable on *more* project layouts and at the last-applicable
  position; still test-gated + HEAD-checked + SC8-bounded) and **T10**
  (auto-resolution surface unchanged in kind, wider in reach); reaffirm **T11**
  (the floor command stays code-owned/deterministic — `resolve_pkg` now resolves
  more shapes but still never guesses) and note the new shapes resolve
  deterministically. Bump **Last reviewed**.
- **`docs/architecture.md`** — `### Task outcome status` and `## State model`:
  the position signal becomes "last *applicable* task" (was "last not-done
  task"); reaffirm **SC8** unchanged; the `### Acceptance run-smoke` /
  `### Acceptance gate enforcement` decisions note flat-layout reach. `SC8`
  itself is unchanged (bounds intact).
- **`.ai-pm/contracts/run-plan.md`** — clear the two `## Out of scope` lines
  (flat-layout reach gap; fuller deliverable-complete signal), update
  `## Acceptance checks` (the "Current bound (honest)" note about enforcing only
  at the literal last task), and add the feature to `## Built/changed by`.

> Per ownership rules, this note proposes only — it does not edit
> `docs/`, the threat-model, the contract, the plan, or any code.
