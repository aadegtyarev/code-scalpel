# Backend re-architecture — design notes

> PM-mandated, deliberate structural re-think. The current backend was written
> "blind" by a weak model before the protocol existed; this note proposes the
> target architecture toward the actual product goal. It is a **design note,
> not a doc rewrite** — `docs/architecture.md` stays the AS-IS, current-truth
> baseline and is only referenced here.

## Goal restated (what "working" means)

code-scalpel must **reliably** get a weak local LLM (default
`qwen2.5-coder-14b`) to produce *actually-working* code under controlled
autonomy. The concrete acceptance gate is **v0.14: 3/3 consistent
`task_solved` on the `notes_cli` benchmark.** Today it is far from that.

## Context

The plan adds (and the diagnosis below proves) one missing backbone concept:
the agent never runs the deliverable the way a user would, so "done" is
declared on proxies (import + unit tests on the easy module). The structural
choice is real and large — it touches how the whole run loop decides *done*,
how multi-language readiness is expressed, and how much of the legacy
`agent.py` monolith must move. The closest existing shape in the codebase is
the `Skill` ABC (`code_scalpel/skills/base.py`) — a per-stack test/lint/format
contract — but it has **no scaffold and no run-smoke/acceptance step**, which
is exactly the gap.

## Proven diagnosis (ground truth — probe-run corpus)

Read from the 107-run `notes_cli` spike (corpus present:
`docs/article/probe-runs/notes_cli*`, 112 run dirs on disk):

- **19% `task_solved`, 76% `user_gave_up`.** The *same commit* flips
  solved/gave_up across repeated runs → nondeterministic, not consistent.
- The dominant *recent* failure (5–7/8 score) is a plausible project that
  **does not actually run**: files exist, unit tests are GREEN, README and
  install succeed — but the `python -m <pkg> add → list` round-trip fails.
- **ROOT CAUSE (behavior-level):** of 52 recent `user_gave_up` runs, **only 1
  (2%) ever invoked the CLI with a real subcommand.** The agent verifies
  *proxies* (package import + `test_storage.py`) and never runs the product.
  Its Definition-of-Done has no step that runs the deliverable as a user would.
- **Concrete coin-flip:** same commit, two runs. SOLVED run had
  `src/notes_cli/__main__.py` + `test_cli.py`; GAVE_UP (7/8) run had neither →
  `python -m notes_cli` fails ("package cannot be directly executed"). The
  *only* difference was two artifacts the model emits nondeterministically.
- **Language-agnostic:** the missing `__main__.py` is Python plumbing (a
  symptom). The real gap — no enforced acceptance/run contract in the DoD —
  recurs identically in Go/JS/Rust.

## Current-state assessment (AS-IS, from `docs/architecture.md` + source)

What exists and where the redesign lands:

| Module | LOC | Role today | Verdict for redesign |
|---|---|---|---|
| `agent.py` (`StepAgent`) | **3289** | the everything-engine: tool loop, `stream_ask`, `code_with_retry`, `run_plan`, narrow passes, compaction, fork detection, plan execution, per-task verification | **Tangled.** The size *is* a redesign driver. The acceptance gate must land inside `run_plan` (line ~1459 verification block), but the loop is buried in a 3289-line class. Strangle, don't big-bang. |
| `runtime.py` (`Runtime`) | 238 | composition channel: owns session+llm+memory+agent; `stream/ask/code_with_retry/fork/flush_upstream` | **Reusable + it IS the TUI seam.** Clean, single-purpose. Keep it the **single** channel, but it is **evolvable under a non-breakage discipline** — the seam may be extended deliberately (new hook, new method), never silently broken (see seam below). |
| `skills/` (`Skill` ABC + registry) | 717 | per-stack **test/lint/format** contract + detect-by-manifest registry | **Reusable seed of the project adapter.** Already has detect + selection + priority. Missing: scaffold + build-install + run-smoke + acceptance declaration. The adapter is a *superset* of Skill, not a rival. |
| `run_plan` (in `agent.py`) | — | per-task loop: dispatch → `_classify_outcome` → verify (`Files:` exist, `Test command:` exit-0, git HEAD advanced) → mark `[✓]` | **The exact insertion point.** A 4th, mandatory verification — *run-smoke of the deliverable* — slots beside the existing three at line ~1470. |
| `code_with_retry` (in `agent.py`) | — | single patch loop: generate→review→apply→test, `debug_pass` on test failure | **Reusable as the self-fix engine.** Acceptance failure routes back here — it already knows how to retry from a failure signal. |
| `policy.py` / trust | 157 | one `TrustLevel` knob gates shell + patch + fork resolution | **Keep.** Acceptance run-smoke is a shell/test action → already governed by trust. No new axis. |
| `fork.py` (delegation) | 987 | trust-driven fork resolution (Human/LocalMeta/Upstream/ReviewedAuto) + batch queue | **Keep, lightly re-aim.** "Which adapter / which expected behavior?" is itself a fork the existing machinery can resolve when ambiguous. |
| `narrow_pass.py` | 63 | one-shot role-specialised LLM call | **Reusable.** "Derive the acceptance command + expected output for this task" is a natural new narrow pass. |
| `state.py` (`AgentState`) | 80 | `STATE.json` atomic persist/load | **Keep.** Acceptance outcome (last run-smoke command + verdict) is one more persisted field. |
| `tools/agent_tools.py` | 1385 | tool dispatch + schemas (`run_tests`, `run_python`, `shell_exec`, …) | **Reusable.** Run-smoke executes through the existing shell/test tools; no new tool primitive needed, only a new *caller*. |
| `tui/` | ~2129 | Textual app | **UX is the asset, not the code.** The TUI *may* be touched (new features, bug fixes) and could even be rewritten from scratch — provided its **UX / ergonomics** are preserved. The lock is on *experience*, not *implementation*. Recommend capturing that UX as an explicit spec first (`docs/ui-guide.md`; see Migration). |

**Honest summary:** the only deeply tangled module is `agent.py`. Everything
else is small and single-purpose and survives the redesign. The redesign is
therefore mostly *additive* (a new adapter abstraction + one acceptance gate)
plus a *targeted strangle* of `run_plan`/`code_with_retry` out of the monolith
— not a ground-up rewrite.

## Target architecture (the new backbone)

Three new/changed pieces: the **ProjectAdapter** abstraction (superset of
`Skill`), the **acceptance gate** in `run_plan`'s DoD, and the **self-fix
loop** routing acceptance failures back to `code_with_retry`. Everything
reorganizes around the question *"did the deliverable actually run?"*.

```
                         ┌──────────────────────────────┐
                         │            TUI                │  UX/ergonomics =
                         │  (textual app — UX preserved, │  the preserved asset
                         │   impl may evolve/be rewritten)│  (not frozen code)
                         └──────────────┬───────────────┘
                                        │  consumes:
                                        │  Runtime.stream / .ask /
                                        │  .code_with_retry / .fork /
                                        │  run-plan progress hooks
                         ════════════════╪════════════════  ← the SEAM
                                        │   (evolvable under a
                                        │    non-breakage discipline:
                                        │    extend deliberately,
                                        │    never break silently)
                                        │
                         ┌──────────────▼───────────────┐
                         │          Runtime              │  composition channel
                         │  (session, llm, memory, agent)│  (kept, clean)
                         └──────────────┬───────────────┘
                                        │
                         ┌──────────────▼───────────────┐
                         │     run_plan loop (strangled  │
                         │     out of agent.py)          │
                         │                               │
                         │  per task:                    │
                         │   dispatch → code_with_retry  │◄──────┐ self-fix
                         │   classify outcome            │       │ route-back
                         │   VERIFY (machine):           │       │ on accept-
                         │    1 Files exist   (exists)   │       │ ance FAIL
                         │    2 Test cmd  0   (exists)   │       │
                         │    3 HEAD advanced (exists)   │       │
                         │    4 ACCEPTANCE   (NEW,       │───────┘
                         │      MANDATORY): adapter      │
                         │      run-smoke vs expected    │
                         └──────────────┬───────────────┘
                                        │ asks
                         ┌──────────────▼───────────────┐
                         │   ProjectAdapter (registry,   │  superset of Skill
                         │   detect-by-manifest)         │
                         │   ┌─────────────────────────┐ │
                         │   │ scaffold(spec)          │ │  ← deterministic,
                         │   │ build_install()         │ │    code-owned
                         │   │ test()        (=Skill)  │ │    profiles
                         │   │ run_smoke(args)         │ │    (not the model's
                         │   │ acceptance_spec(task)   │ │     whim)
                         │   └─────────────────────────┘ │
                         │   PythonCliAdapter  (first)   │
                         │   NodeCliAdapter    (sketch)  │
                         └───────────────────────────────┘
```

**Reorganization of existing concerns around the gate:**

- **narrow-pass** gains one role: *derive the acceptance command + expected
  observable for this task* (when the task doesn't declare it). One cheap
  one-shot call, same pattern as the existing skill-annotator pass.
- **trust / fork-delegation** is unchanged in mechanism: run-smoke is a
  shell/test action already gated by trust; "which adapter / what counts as
  acceptance?" when genuinely ambiguous is resolved through the existing
  `fork()` API, not a new path.
- **run-plan loop** gains the 4th mandatory verification and the self-fix
  route-back; the existing three machine checks stay.
- **state** persists the last run-smoke command + verdict for resume.
- **TUI surfacing — preserve the UX, evolve the seam with care:** acceptance is
  surfaced through the *existing* `on_task_end` outcome (a `done` now genuinely
  means "ran"), so the redesign needs **no** TUI change. That is the *safe
  default*, not a freeze: if a richer surfacing (e.g. a distinct "acceptance
  failed → self-fixing" signal) proves worth it, the seam **may** gain a new
  hook — done deliberately, with the TUI's consumption updated in the same
  change so nothing breaks silently. The UX/ergonomics are the asset to
  preserve; the `Runtime` contract is evolvable under that non-breakage
  discipline.

## The adapter contract (concrete shape)

A `ProjectAdapter` is the **single deterministic, code-owned authority** on how
to build / test / run / scaffold one project *type*. It is a superset of the
existing `Skill` ABC (`test()` is today's `test_cmd`); the redesign *extends*
`Skill` rather than introducing a parallel hierarchy.

Each adapter must provide:

| Method | Returns | Purpose |
|---|---|---|
| `detect(root)` | `bool` | manifest-based, fast, no subprocess (already in `Skill`) |
| `scaffold(spec)` | argv / file plan | deterministic project skeleton — **kills the `__main__.py` coin-flip** by owning the entrypoint plumbing instead of leaving it to the model |
| `build_install()` | argv | how to make the deliverable runnable (`pip install -e .`) |
| `test()` | argv | unit-test command (= today's `Skill.test_cmd`) |
| `run_smoke(args)` | argv | run the **actual deliverable** as a user would (`python -m <pkg> <args>`) |
| `acceptance_spec(task)` | `(command, expected_observable)` | how a task declares what "actually works" means; derived from the task or via the new narrow pass |

**Selection** reuses the existing registry: `detect()` by manifest, `priority`
order, first-runnable wins. Project/task *type* (cli vs lib vs service)
narrows which adapter variant applies.

**Adding a new language** = subclass + register one adapter; no run-loop edit.

**Worked example — `PythonCliAdapter` (first implementation + debug target):**

```
detect          → pyproject.toml | requirements.txt | setup.py present
scaffold        → ensure src/<pkg>/__init__.py, __main__.py (argparse → main),
                  pyproject [project.scripts] / -m entrypoint
build_install   → ["pip","install","-e","."]
test            → ["pytest","-x","--tb=short","--no-header","-q"]   (today's PythonSkill)
run_smoke(args) → ["python","-m","<pkg>", *args]
acceptance_spec → e.g. ("python -m notes_cli add 'x' && python -m notes_cli list",
                        expected: the added note appears in list output)
```

**Second language sketch — `NodeCliAdapter` (proves the abstraction is real):**

```
detect          → package.json present
scaffold        → bin/<cli>.js + package.json "bin" field
build_install   → ["npm","install"]
test            → ["npm","test"]
run_smoke(args) → ["node","bin/<cli>.js", *args]   (or the "bin" name)
acceptance_spec → ("node cli add 'x' && node cli list", expected: note present)
```

The two share zero hardcoded commands in the run loop — every build/test/run
string lives behind `detect()`-selected adapter methods. That is the proof the
abstraction is real, not a Python-shaped hole.

## How this closes the diagnosis

| Diagnosis finding | Mechanism that kills it |
|---|---|
| 2% problem — agent **never runs the deliverable** | **Acceptance gate** (verification #4): a task cannot be `done` until `adapter.run_smoke(...)` passes against `acceptance_spec`. "Done on proxies" becomes structurally impossible. |
| `__main__.py` **coin-flip** (nondeterministic plumbing) | **Adapter `scaffold()` determinism**: the entrypoint is code-owned, not model-emitted-by-whim. Same plumbing every run. |
| 19% solved / **nondeterministic** across runs | **Self-fix loop**: acceptance failure routes back to `code_with_retry` (the model fails its own machine check and iterates — the "controlled autonomy" the product promises). Converges runs toward 3/3 instead of leaving success to sampler luck. |
| Failure is **language-agnostic** | The contract lives in the **adapter abstraction**, debugged on Python but designed for Node/Go/Rust now — the gap can't silently reappear per-language. |

## Genuine structural forks → options + recommendation

### Fork 1 — Adapter packaging: extend `Skill` vs parallel `ProjectAdapter` hierarchy

- **A. Extend the existing `Skill` ABC** (add `scaffold/build_install/run_smoke/acceptance_spec`).
  - Pros: reuses detect + registry + priority + `/skills` UI; one mental model;
    smallest diff; component-skills (Postgres) coexist unchanged.
  - Cons: `Skill` grows; "skill" name now also means "how to run a product".
- **B. New `ProjectAdapter` hierarchy alongside `Skill`.**
  - Pros: clean naming; acceptance concerns isolated.
  - Cons: two registries, two detect paths, two things the agent must keep in
    sync — exactly the kind of divergence the `Runtime` "single channel" lesson
    warns against; doubles the surface for a small gain.
- **Recommendation: A.** Extend `Skill` into the adapter. The seed is already
  there (detect + registry + priority); a parallel hierarchy re-litigates
  selection logic for no real benefit. Rename in docs to "project adapter";
  keep the class lineage.

### Fork 2 — How acceptance expectations are specified

- **A. Adapter built-in default per type** (e.g. python-cli ⇒ "the CLI runs
  without error and the help/subcommand exits 0").
  - Pros: zero per-task authoring; deterministic; works on `notes_cli` today.
  - Cons: weak signal — "exits 0" passes for a CLI that does nothing useful.
- **B. Task-declared `Acceptance:` field** in `TASKS.json`/`TASKS.md` (a
  command + an expected observable substring), mirroring the existing
  `Test command:` / `Files:` fields.
  - Pros: precise (catches the add→list round-trip); reuses the existing
    task-field + verification plumbing; human/PM-inspectable in the plan.
  - Cons: someone/something must author it.
- **C. Narrow-pass-derived** acceptance spec when the task omits one.
  - Pros: no authoring burden; same pattern as the skill-annotator pass.
  - Cons: a *model-derived* check re-introduces nondeterminism into the gate.
- **Recommendation: B as the contract, C as the fallback, A as the floor.**
  Prefer an explicit task-declared `Acceptance:` (deterministic, the real
  round-trip). When absent, derive once via narrow pass (C) and **write it back
  into the plan** so it becomes deterministic on the next run (same
  write-back-the-decision discipline `run_plan` already uses for skill
  annotation). A never lets the gate be skipped — it is the minimum.

### Fork 3 — Decomposing `agent.py`: full decompose vs strangle vs parallel backend

- **A. Big-bang decompose** the 3289-line `StepAgent` before adding the gate.
  - Pros: clean target.
  - Cons: huge, risky, blocks the v0.14 outcome on a refactor with no user-
    visible payoff; the corpus says the bug is behavioral, not structural-debt.
- **B. Incremental strangle**: extract `run_plan` (and later `code_with_retry`)
  into their own modules *as* the acceptance gate lands, leaving the rest of
  `agent.py` untouched until a feature needs it.
  - Pros: each step shippable; the gate lands fast and provable on `notes_cli`;
    `agent.py` shrinks opportunistically.
  - Cons: `agent.py` stays large for a while.
- **C. Parallel new backend behind the `Runtime` seam**, swap when ready.
  - Pros: clean room.
  - Cons: two backends to keep behavior-identical through **one** `Runtime`
    channel — the exact channel-divergence failure mode the project already
    paid for once; highest risk. (This objection rests on the *single-channel*
    invariant, **not** on the seam being frozen — the seam is evolvable; what
    it cannot tolerate is two divergent backends feeding it.)
- **Recommendation: B (unchanged).** Strangle `run_plan` out first (it's the
  gate's home), prove 3/3 on `notes_cli`, then peel more only when justified.
  Reject C — but on its **own** merits, not on a "frozen seam" premise: a
  parallel backend re-creates the channel divergence the `Runtime`
  **single-channel** decision exists to prevent. The seam being now evolvable
  (under the non-breakage discipline) does **not** rehabilitate C — two
  behavior-divergent backends are the risk, regardless of how the seam itself
  may change.

## Migration path (protocol-plannable features, each shippable)

Framed so `/pm-plan` can pick each up as a feature. Order is dependency-driven;
every step is independently shippable and preserves the TUI's UX/ergonomics
(the `Runtime` seam may evolve under the non-breakage discipline, but no step
below requires it to).

0. **`feat/capture-tui-ux-spec`** *(de-risks every later seam change; not on
   the v0.14 critical path but cheap and high-leverage)* — promote
   `docs/ui-guide.md` from its bootstrap extractor-draft state into a real,
   authoritative **UX / ergonomics spec** (layout, modes, keybindings, card
   behaviors, the streaming/focus model — the *experience* contract). This is
   what makes the TUI safely **evolvable or even rewritable from scratch**, and
   what lets any future `Runtime`-seam change be verified against an explicit
   experience baseline instead of folklore. Pure docs; no code. *(Owner:
   `pm-architect` finalizes `docs/ui-guide.md`.)*
1. **`feat/project-adapter-abstraction`** — extend `Skill` into the adapter
   contract (add `scaffold/build_install/run_smoke/acceptance_spec`),
   implement `PythonCliAdapter`, register it. No run-loop change yet; pure
   additive, fully unit-testable. *(Preserve: registry, detect, PythonSkill.)*
2. **`feat/acceptance-gate-run-plan`** *(FIRST that moves the needle — propose
   to PM as the lead feature)* — add verification #4 to `run_plan`: after the
   existing three checks, `adapter.run_smoke()` vs the task's acceptance spec;
   a failing round-trip flips the task to `failed`. Strangle `run_plan` into
   its own module as part of this. **Acceptance criterion of the feature
   itself: `notes_cli` 3/3 `task_solved`.** *(Preserve: existing three checks,
   `_classify_outcome`.)*
3. **`feat/acceptance-self-fix-loop`** — on acceptance failure, route back to
   `code_with_retry` with the run-smoke output as the failure signal (bounded
   retries, same shape as `debug_pass`). This is what turns "fails the gate"
   into "fixes itself" — the consistency lever toward a *stable* 3/3.
4. **`feat/acceptance-spec-in-tasks`** — add the task-declared `Acceptance:`
   field + the narrow-pass fallback with write-back (Fork 2 B/C/A). Makes the
   gate precise beyond the python-cli default.
5. **`feat/node-cli-adapter`** — second adapter, to prove (and lock in via
   tests) language-agnosticism. Lower priority; not on the v0.14 path.
6. *(Opportunistic, not gating)* further `agent.py` strangling as features
   touch it — never a standalone big-bang.

**Preserve vs rewrite:** preserve `policy`/trust, `fork`, `narrow_pass`,
`state`, `tools`, `skills` registry, and — above all — the **TUI's
UX/ergonomics** (the asset; the TUI *code* may be touched or rewritten so long
as that experience is preserved, ideally against the captured `docs/ui-guide.md`
spec). Keep `Runtime` as the **single** channel; it may **evolve** under the
non-breakage discipline, but is not duplicated or forked. The backend redesign
itself only *moves* `run_plan`/`code_with_retry` (strangle out of `agent.py`)
and *adds* the adapter superset + the gate — no ground-up backend rewrite.

## New goals / intentions (the "why", for future sessions)

- **The product's promise is a deliverable that actually runs**, not a
  plausible-looking project. "Done" must mean "a user could run it and observe
  the expected behavior" — verified by machine, not asserted by the model.
- **Determinism is the product.** The whole value proposition is reliability
  from a weak model. Anything left to the model's whim (entrypoint plumbing,
  whether to run the deliverable) becomes a coin-flip and must be moved into a
  deterministic, code-owned adapter.
- **Controlled autonomy = the model fails its own machine check and iterates.**
  The self-fix loop is not a safety net bolted on; it is the literal mechanism
  by which the product delivers "controlled autonomy" — bounded, machine-gated
  self-correction.
- **Multi-language is a first-class design constraint, debugged on Python.**
  The acceptance/run contract lives in the adapter *because* the failure is
  language-agnostic. Python is the first implementation, never the only shape.
- **The TUI's UX is the asset — the implementation is not frozen.** What must
  be preserved is the *experience* (ergonomics, layout, interaction model), not
  any particular line of `tui/`; capture it as a spec (`docs/ui-guide.md`) and
  the TUI becomes safely evolvable or even rewritable. The backend re-think
  lives behind the `Runtime` seam, which stays the **single** channel and may
  **evolve deliberately** under a non-breakage discipline — never silently
  broken, never forked.

## Plan notes (for `/pm-plan`)

- Feature 2 (`feat/acceptance-gate-run-plan`) should carry an explicit
  **Product Contract `## Must not break`**: a `done` task means run-smoke
  passed (no regression to proxy-only "done").
- Feature 2's plan should record the **v0.14 outcome gate** (`notes_cli` 3/3)
  as its acceptance — this is the existing "outcome-driven release gate"
  decision (`docs/architecture.md` → Architectural decisions) finally getting
  teeth.
- `docs/architecture.md` will need a post-coding update once the adapter +
  gate land (new Architectural decision + File-layout entries) — that is the
  normal "Docs to update" handoff, **not** part of this design note.
