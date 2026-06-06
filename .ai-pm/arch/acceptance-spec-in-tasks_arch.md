# Acceptance spec in tasks — design notes

> Focused per-feature design note for `feat/acceptance-spec-in-tasks` — step 4
> of the backend redesign (`.ai-pm/arch/backend-redesign_arch.md`, migration
> item 4; Fork 2 "B contract / C fallback / A floor"). This is a **design
> note, not a doc rewrite**: `docs/architecture.md` stays AS-IS and is
> referenced. The post-coding "Docs to update" handoff (a new Architectural
> decision row, a new `SCn`, the T11 threat-model update) is the normal
> handoff, **not** authored here — this note only specifies *what* those
> updates must say so the doc-owner spawn can land them.

## Context

Feature 2 (`feat/acceptance-gate-run-plan`, PR #169, merged) shipped
verification #4 as **observational only**: `_verify_acceptance`
(`code_scalpel/plan_verify.py:120-159`) runs the deliverable's run-smoke,
records the verdict + reason, surfaces a card — but **never demotes**
(`plan_verify.py:157-159`, "Plumbing only: record + surface, never demote").
The reason it stayed observational is a real regression that forced the PM's
"plumbing only" decision: `PythonCliAdapter.detect` fires on **any** Python
project (`python_cli_adapter.py:84-85`, delegating to `PythonSkill.detect`), so
a demoting gate would wrongly fail every `/go` run over a Python **library**
that has no runnable `python -m <pkg>` deliverable (`plan_verify.py:17-23`).

This feature gives the gate its teeth: **flip verification #4 from record-only
to ENFORCING (demote done→failed) where an acceptance expectation exists, while
never wrongly failing projects that have none.** The discriminator is the whole
problem; the parent note's Fork 2 already names its shape — task-declared (B) →
narrow-pass-derived (C) → adapter default-floor (A) — and this note locks the
generic, language-agnostic mechanism for it.

The structural choice is real on four axes (resolutions below), all bound by two
PM constraints that are **binding, not negotiable**:

1. **Generality first.** notes_cli is the *proof*, never the target. The
   spec-derivation, the "build the run command from args", and the
   enforcement-gating MUST live on the generic ProjectAdapter contract +
   run-loop seam so feature 5's `NodeCliAdapter` (Go, etc.) plugs in with **no
   run-loop edit**. The run-loop carries ZERO language-specific assumptions —
   every "how to run this deliverable" string comes from the `detect()`-selected
   adapter (parent note: "every build/test/run string lives behind
   `detect()`-selected adapter methods. That is the proof the abstraction is
   real, not a Python-shaped hole" — `backend-redesign_arch.md:203-205`).
2. **Model-derived checks are ARGS-ONLY (PM decision).** When a task declares no
   acceptance expectation, the narrow pass may return ONLY the subcommand args +
   an expected observable substring — NEVER a free-form shell command. The
   **adapter** builds the actual argv from those args (python-cli →
   `python -m <pkg> <args>`; node-cli → `node <bin> <args>`). The model can never
   inject arbitrary shell. Execution stays through the existing gated `execute()`
   path (`plan_verify.py:228-236`): policy hard-blocks (SC1/SC2), bwrap sandbox
   (SC3), cwd-pinned, `trust="yolo"` as a plan-owned check.

## Adjacent implementations (verified this turn)

1. **The observational gate** — `_verify_acceptance` /
   `_run_smoke` (`plan_verify.py:120-244`). `_run_smoke` already: calls
   `adapter.acceptance_spec(task)` (`:206`), handles `ValueError` →
   `pkg-unresolvable` (`:207-211`), handles `spec is None` → `noop` (`:212-216`),
   re-derives argv to strip shell metacharacters (`shlex.join(shlex.split(...))`,
   `:226`), executes through gated `execute(..., trust="yolo", ...)` (`:228-236`),
   and **already checks the `expected` observable** when non-empty (`:242-243`,
   "`expected and expected not in result.output` → failed/`expected-missing`").
   That `expected` check is the answer to the spawn's question-2 confirmation: it
   is **present in merged code** — feature 2 review finding 2 already landed it.
   What this feature changes is *whether the verdict demotes*, plus *where the
   spec comes from* — not the run-smoke mechanics.
2. **The adapter's floor `acceptance_spec`** —
   `PythonCliAdapter.acceptance_spec` (`python_cli_adapter.py:111-126`)
   **currently IGNORES `task`**: it always returns the default-floor
   `(f"python -m {pkg} --help", "")`. The signature already takes the task
   (`base.py:203`, `acceptance_spec(self, task: object)`), so feature 4 enriches
   the *body* (precedence B→C→A) without touching the run-loop call site.
3. **`run_smoke(args)` — the generic argv builder** —
   `PythonCliAdapter.run_smoke(args)` (`python_cli_adapter.py:96-109`) already
   turns *args* into argv: `["python", "-m", pkg, *shlex.split(args)]`. This is
   exactly the "adapter builds argv from args" primitive constraint 2 requires;
   the args-only narrow-pass result feeds straight into it. No new method needed.
4. **The skill-annotation write-back** — `_annotate_plan` (`plan_loading.py:134-171`):
   the canonical "fire one LLM pass before the loop, write the decision back,
   re-parse + re-hash" pattern (`_atomic_write` + `parse_tasks_md` +
   `_hash_text`, `:154-165`), with finding-7's guard that the no-change path
   returns the **existing typed tuple** rather than re-parsing (which would drop
   typed `Task` fields, `:142-147`). This is the template for the spec write-back
   (resolution 3) — and finding 7 is the exact trap the round-trip fix must dodge.
5. **The narrow-pass primitive** — `NarrowPass(name, system_prompt, temperature,
   output_schema)` (`narrow_pass.py:25-47`). `output_schema` gives
   sampler-enforced JSON (`:38-42`, "the model is guaranteed to emit valid JSON
   conforming to the schema, no prompt-begging"); the agent has a helper to
   execute one. This is the C-derivation engine — and the args-only constraint
   becomes a *schema*, mechanically enforced, not a prompt plea.
6. **The typed `Task.acceptance` field** — `Task.acceptance: tuple[str, ...]`
   (`plan.py:58`), parsed by `task_from_json` (`plan.py:184,197`), written by
   `serialize_tasks_json` (`plan.py:260`) and `render_tasks_markdown`
   (`plan.py:288-291`). **The round-trip gap:** `parse_tasks_md`
   (`plan.py:63-93`) does NOT parse `Acceptance:` back — markdown round-trip
   drops it (resolution 3 must fix this, or target JSON).

## Behavioral risks in this area

- **No feedback loop introduced.** Demotion is a status flip on the per-task
  outcome; it subscribes to nothing and re-triggers nothing. The
  failure-output → `code_with_retry` route-back (where a loop *would* appear) is
  **feature 3**, explicitly out of scope — this feature only demotes done→failed,
  it does not attempt repair (parent note migration items 3 vs 4).
- **The C-derivation is a model-derived input into the gate** — the one place
  determinism is at risk. Mitigated three ways, in order: (a) args-only schema
  so the worst case is bad *args*, never a shell command (constraint 2); (b)
  write-back so the derivation runs **once** and is deterministic on every later
  run (resolution 3, the parent note's "write it back into the plan so it
  becomes deterministic on the next run", `backend-redesign_arch.md:249-254`);
  (c) the adapter, not the model, owns argv assembly — `python -m <pkg> <args>`
  is code-owned even when `<args>` is model-derived.
- **Over-failing libraries is the regression to avoid** — the exact failure that
  forced feature 2 to plumbing-only. The applicability discriminator
  (resolution 1) is designed so a library reliably yields *not-applicable* and
  stays observational; getting that wrong re-creates the merged-and-reverted bug.

---

## Resolution 1 — the enforcement-gating signal (CLI-vs-library discriminator)

**Orchestrator lean:** enforce (demote) only when an *applicable* acceptance
spec exists — task-declared (B) OR narrow-pass-derived-and-marked-applicable (C);
stay observational when only the adapter default-floor (A) applies, or the
derivation returns not-applicable (library). The derivation's `applicable: bool`
IS the discriminator.

**Confirmed — "enforce iff an applicable spec exists" is the right rule**, with
three sharpenings on *where the decision lives* and *how a library yields
not-applicable*.

### Variant A — applicability is a property of the *spec result* (recommended)

Verification #4 enforces (demotes) iff the spec the gate is about to run is
**applicable**, where applicable means one of:
- **B (task-declared):** the task carries a non-empty `Task.acceptance`
  (`plan.py:58`) — a human authored a runnable expectation, so a CLI deliverable
  is intended. Always applicable, always enforcing.
- **C (derived + applicable):** the narrow pass ran and returned
  `applicable: true` (a runnable CLI deliverable exists) AND was written back.
  Enforcing.
- **A (default-floor) / C-not-applicable / no spec:** observational (feature-2
  behavior). The floor `python -m <pkg> --help` stays record-only — exactly
  because `PythonCliAdapter.detect` over-fires on libraries; the floor is *not*
  evidence of CLI intent, so it must never demote.

**Where the applicability decision lives — the spec result, surfaced through the
adapter, consumed by the run-loop.** Three-layer split, no layer overreaching:
- The **derivation** (narrow pass) *produces* `applicable` — it is the only
  thing that can judge "is there a runnable CLI deliverable here?" by inspecting
  the task. This is the single source of the library-vs-CLI judgment for the C
  path.
- The **adapter** *carries it* in the spec return shape (resolution 2): the gate
  asks the adapter for a spec and the adapter hands back applicability with it,
  so the run-loop never type-switches on python-vs-node.
- The **run-loop** *acts on it* — one branch: `enforce = spec.applicable`. The
  run-loop holds **zero** language knowledge; it asks the adapter, reads one
  bool, demotes or records. This is the generality seam (constraint 1).

**How a library reliably yields not-applicable without overfitting to python.**
The judgment is *semantic* ("does this task ship a runnable command-line
deliverable?"), not python-syntactic, so it lives in the **narrow-pass schema +
prompt**, which is language-neutral:
- The narrow pass returns `applicable: false` for a task whose deliverable is an
  importable library / module with no CLI entrypoint — "no runnable CLI
  deliverable". This is a property of the *task's intent*, identical for a Python
  library, a Go package, or an npm lib.
- The floor (A) is **never** treated as applicability evidence — so even when
  `PythonCliAdapter` over-detects a pure library, the gate stays observational
  unless B or applicable-C explicitly says a CLI exists. This is what structurally
  prevents the feature-2 regression: applicability is an *opt-in CLI signal*, not
  a *default*.
- notes_cli (no human-declared acceptance) yields applicable-C via the derived
  path — see resolution 5.

**Why not put applicability on the adapter's `detect` or as a new adapter
method.** `detect` answers "is this a python project?", not "does this task ship
a CLI?" — overloading it re-creates the over-detection bug at a different layer.
A separate adapter method would force the adapter to re-judge task intent the
narrow pass already judged. The spec *result* is the correct, single home.

**Recommendation: Variant A.** Applicability is a field on the spec result, born
in the derivation, carried by the adapter, read once by the run-loop.

---

## Resolution 2 — the generic acceptance-spec shape + adapter responsibility

**Orchestrator lean:** extend `acceptance_spec(task)` to consume the task with
precedence B→C→A; reuse `run_smoke(args)` for argv assembly; narrow pass returns
`{applicable, args, expected}`; the spec the gate runs is
`(adapter-built-command, expected_substring)`.

**Confirmed**, with the spec shape made explicit so `NodeCliAdapter` needs zero
run-loop change.

### The generic contract shape

Today `acceptance_spec(task) -> tuple[str, str] | None` (`base.py:203`,
`python_cli_adapter.py:111`). The current 2-tuple `(command, expected)` cannot
carry applicability, so the run-loop would have to infer it — re-introducing
language knowledge into the loop. **Extend the return to a small frozen
dataclass** (recommended over widening the tuple — a 4th tuple slot is
position-fragile and the gate already unpacks `raw_command, expected = spec` at
`plan_verify.py:225`):

```
@dataclass(frozen=True)
class AcceptanceSpec:
    command: str            # adapter-built argv-string (code-owned assembly)
    expected: str           # observable substring; "" = exit-0-only (floor)
    applicable: bool        # True ⇒ enforcing (B or applicable-C); False ⇒ observational
    source: Literal["declared", "derived", "floor"]  # provenance, for the card + reason + feature-3
```

`acceptance_spec(self, task) -> AcceptanceSpec | None`. The adapter's body
implements the **precedence**:
1. **B** — task declares acceptance (`task.acceptance` non-empty): build the
   command from the declared args via `run_smoke(args)`, `applicable=True`,
   `source="declared"`. (See resolution 4 for the "route through the adapter
   where possible" refinement — even human-declared specs should be args, built
   by the adapter, for the same generality.)
2. **C** — no declaration but a written-back derived spec is present: use it,
   `applicable=<the derived bool>`, `source="derived"`.
3. **A** — neither: the floor `python -m <pkg> --help`, `applicable=False`,
   `source="floor"`. Observational, exactly as today.

### Adapter responsibility — argv from args, generically

The adapter is the **single owner** of "args → argv". `run_smoke(args)` already
does this for python-cli (`python_cli_adapter.py:96-109`); **reuse it** — the B
and C paths call `self.run_smoke(declared_or_derived_args)` to build `command`,
so the python-specific `python -m <pkg>` prefix lives only inside the adapter.
`NodeCliAdapter` (feature 5) ships its own `run_smoke(args)` →
`["node", bin, *shlex.split(args)]` and its `acceptance_spec` reuses it
identically; **its `AcceptanceSpec` flows through the same run-loop branch with
no edit** — that is the generality proof.

The run-loop's contract is reduced to: `spec = adapter.acceptance_spec(task)`;
run `spec.command`; if `spec.applicable` and verdict≠passed → demote, else
record. No `python -m`, no `node`, no language string anywhere in the loop.

### `expected` is checked — confirmed

The `expected` observable is **already** enforced in merged code
(`plan_verify.py:242-243`): a non-empty `expected` must appear in run-smoke
output or the verdict is `failed`/`expected-missing`. The floor's
`expected == ""` stays exit-0-only (`:240-244`). Feature 4 adds nothing here
except *supplying* a meaningful `expected` via B/C (the add→list round-trip
substring) instead of the floor's empty sentinel — which is precisely what turns
"exits 0" into a real signal (parent Fork 2 A-con: "'exits 0' passes for a CLI
that does nothing useful", `backend-redesign_arch.md:239`).

**Recommendation: Variant as stated** — `AcceptanceSpec` dataclass return,
adapter owns precedence + argv assembly via `run_smoke`, run-loop reads
`.command`/`.expected`/`.applicable` only.

---

## Resolution 3 — the narrow-pass derivation (Fork 2 C) + write-back

**Orchestrator lean:** new `NarrowPass` with `output_schema =
{applicable, args, expected}`; run once when a task lacks declared acceptance;
write back into the task's acceptance field (mirror `_annotate_plan`); fix the
`parse_tasks_md` round-trip gap. Pick write-back target.

**Confirmed**, with the round-trip fix and run location decided.

### The narrow pass — args-only, schema-enforced

A new `NarrowPass(name="acceptance_spec", output_schema=...)` with the schema
**mechanically enforcing constraint 2**:

```
{ "applicable": bool, "args": string, "expected": string }
```

- `args` is the subcommand args ONLY — e.g. `add "buy milk" && list` is **not**
  permitted as free text; the schema field is the args the adapter will splice
  after its own `python -m <pkg>` / `node <bin>` prefix. (For a round-trip
  expectation the adapter, not the model, owns chaining — see the security note
  in resolution 4: a `&&`-joined free command is exactly what the args-only rule
  forbids. The derivation returns the *args of the observing invocation*; if the
  product needs a setup+observe sequence, that is a richer spec shape the
  adapter composes from args, never a model-emitted shell line.)
- The schema-loose lesson from `PLAN_JSON_SCHEMA` (`plan.py:134-141`: 14b ignores
  `pattern`/`minItems`, tight schemas backfire) applies — keep the schema to the
  three-field top-level shape; enforce "args only, no shell metacharacters" in
  the **adapter's argv build** (`shlex.split` already rejects nothing but the
  adapter never passes the string to a shell — `plan_verify.py:226` re-derives
  via `shlex.join(shlex.split(...))`, so metacharacters become literal argv
  tokens, not shell operators). The schema constrains *shape*; the adapter
  constrains *execution*. Belt and suspenders.

### Write-back target — JSON canonical, with the markdown round-trip fixed

**Recommendation: write back to the JSON representation (`TASKS.json`) as the
canonical target, AND fix `parse_tasks_md` to parse `Acceptance:` so the
markdown view round-trips losslessly.** Both, because:
- JSON is already the source of truth (`plan.py:5-8`, "canonical
  machine-readable format … Read first by the runtime";
  `serialize_tasks_json` already writes `acceptance`, `plan.py:260`). Writing the
  derived spec there makes it deterministic on the next run via
  `parse_tasks_json` → `task_from_json` (`plan.py:184,197`), which **already**
  reads it back. This path works **today** with no parser change.
- BUT the live run-loop's plan-modification sentinel and the human-readable view
  go through markdown (`_resolve_task_list`, `plan_loading.py:51-79`, re-renders
  markdown and hash-compares it each iteration; `_annotate_plan` writes markdown
  via `_atomic_write` + `parse_tasks_md`, `plan_loading.py:154-160`). The
  `_annotate_plan` template **re-parses markdown** after write-back — and
  `parse_tasks_md` drops `Acceptance:` (`plan.py:63-93`), so a markdown-targeted
  write-back that re-parses would **lose the spec it just wrote** (finding-7's
  trap, `plan_loading.py:142-147`, generalized).
- **The minimal-risk fix:** target JSON for the durable write-back, and make the
  re-parse path finding-7-safe — return the **already-typed** task tuple (with
  the derived `acceptance` filled) rather than re-parsing from markdown, exactly
  as `_annotate_plan` does on its no-change path (`plan_loading.py:142-147,
  165`). Then `parse_tasks_md` learning `Acceptance:` is a **nice-to-have for
  hand-edit fidelity**, not a correctness dependency — recommend doing it (small,
  symmetric with `render_tasks_markdown`'s `Acceptance:` writer at
  `plan.py:288-291`) but it is not on the critical path if the typed-tuple
  return is used.

### Where the derivation runs in the loop — pre-task, beside skill annotation

**Recommendation: run it as a pre-loop pass, the same place + shape as skill
annotation** (`_pre_loop_passes` / `_annotate_plan`, `plan_loading.py:82-171`),
NOT at verify time. Reasons:
- **Determinism.** A pre-loop, write-back-once derivation means the spec is fixed
  before any task runs and is *the same on resume / re-run* — the parent note's
  whole "write it back so it becomes deterministic" discipline
  (`backend-redesign_arch.md:249-254`). A verify-time derivation would re-run the
  model per task-completion, re-introducing per-run nondeterminism into the gate
  — the exact thing Fork 2 C's con warns against (`:248`).
- **Visibility.** Pre-loop runs surface through the existing `on_tool_executed`
  card seam (`_emit_annotate_card`, `plan_loading.py:174-184`) — the user sees
  the derived spec before tasks run, can inspect/edit it (and per resolution 4's
  forward note, *should* be able to before first yolo execution).
- **Reuse.** It slots beside the skill-annotation gate in `_pre_loop_passes`
  (`plan_loading.py:104-107`): "if a task lacks declared acceptance, fire the
  derivation pass, write back, re-hash" — verbatim the annotation shape.

**Plan should be updated to:** gate the derivation behind a config flag
mirroring `auto_annotate_plan` (`plan_loading.py:104`) so a hermetic / headless
caller can disable the LLM pass; and run it only for tasks where
`not task.acceptance` (B already covers the rest).

---

## Resolution 4 — security / provenance (resolve the T11 forward-flag)

**Orchestrator lean:** model-derived = args-only → adapter builds argv → gated
`execute()` → no new boundary beyond T11; human-declared = trusted like Test
command. Update the threat-model.

**Confirmed that this fully addresses the deferred provenance question, with one
residual risk surfaced for the PM** (it is a *reduced* risk, not zero).

### Why args-only closes the T11 forward-flag

Feature 2's T11 forward note (`docs/threat-model.md:83`, and the Review note
`:112-118`) deferred exactly this: "feature 4's task-declared / narrow-pass-derived
acceptance commands would re-introduce model-derived text at yolo — a separate
provenance question to scope there". The args-only design **answers it**:
- The model never emits a shell command. It emits **args** (schema-enforced,
  resolution 3). The **adapter** builds the argv (`python -m <pkg> <args>` /
  `node <bin> <args>`), so the executable verb is code-owned; only the arguments
  are model-influenced.
- Execution stays on the **existing** boundary — `execute(..., trust="yolo",
  sandbox=..., shell_exec_timeout=...)` (`plan_verify.py:228-236`), which is
  `policy.decide`-gated (SC1), cwd-pinned + escape-hard-blocked (SC2), and
  bwrap-sandboxed (SC3) per `docs/architecture.md:545-561`. The gate already
  re-derives argv via `shlex.join(shlex.split(...))` (`plan_verify.py:226`) so
  metacharacters in the args become **literal argv tokens, never shell
  operators** — `add "x"; rm -rf ~` becomes the single arg string, not two
  commands. **No new boundary beyond T11.**
- Human-declared (B) acceptance is **trusted like the existing `Test command:`
  field** that already runs at yolo (`agent.py` `_verify_task_test_command`,
  precedent cited in `acceptance-gate-run-plan_arch.md:308-314`): the user
  authored it and accepted the plan.

### Refinement (constraint 2's "route through the adapter where possible")

Even **human-declared** specs should be expressed as args and built by the
adapter where possible, for the same generality (constraint 2). This narrows the
trust surface uniformly: whether the args came from a human or the model, the
*verb* is always adapter-code-owned, never a free-form shell line. A task that
genuinely needs a raw command (escape hatch) is a PM-scoped exception, not the
default — and if kept, it is human-provenance only, never model-reachable.

### Residual risk for the PM (surfaced, not solved here)

The args-only rule reduces the model's reach from "arbitrary shell" to
"arbitrary args to an approved verb" — but **not to zero**:
- **Args still reach a yolo shell on a skeptic run.** The args are model-derived
  text executed sandboxed/policy-blocked, but bwrap is best-effort (SC3 degrades
  to policy-only when userns is restricted, `docs/architecture.md:556-561`). On a
  policy-only host, a model-derived arg to a real CLI runs with project-RW. The
  blast radius is "the deliverable run with odd args", not "arbitrary command",
  but it is non-zero.
- **Mitigation already designed in:** write-back + pre-loop surfacing
  (resolution 3) means the derived args are **inspectable before first
  execution** — the user sees the card before tasks run. Recommend the plan make
  the derived-spec card explicit ("derived acceptance: `<command>` — runs at
  /go") so the user can edit/reject before it executes, the parent note's
  "controlled autonomy" principle applied to the spec itself.

### Threat-model update this feature must trigger (doc-owner handoff, not authored here)

The post-coding "Docs to update" handoff must:
- Update **T11** (`docs/threat-model.md:83`) — replace the *Forward* clause with
  the resolved state: model-derived acceptance is **args-only**, the adapter
  builds the argv, execution stays on the SC1/SC2/SC3 boundary; residual = "args
  (not commands) reach the yolo shell, surfaced for inspection pre-run".
- Add a **new threat row** (T12) for the narrow-pass-derived-args provenance, or
  fold it into T11 — recommend a distinct T12 ("model-derived acceptance *args*
  executed at yolo") so the risk register stays granular, mitigated by the
  args-only constraint + pre-run surfacing, referencing the **existing**
  SC1/SC2/SC3 (no new `SCn` is required — the args-only rule is enforced by the
  adapter's argv assembly, which is implementation, not a new enforceable
  cross-cutting constraint; if the PM wants it as a stable rule, add **SC7**
  "model-derived acceptance input is args-only; argv assembly is adapter-owned,
  never a model-emitted shell string"). Flag both options for the doc-owner /PM.
- Bump **Last reviewed** to the feature's merge date.

**Confirmed** — args-only fully addresses the deferred provenance question; the
residual (args, not commands, at yolo, sandboxed + surfaced) is documented for
the PM, not silently accepted.

---

## Resolution 5 — notes_cli 3/3 + the generality proof

**Confirmed the design achieves both.**

- **notes_cli 3/3 via the derived (args-only) path.** notes_cli has no
  human-declared acceptance, so it goes B-absent → **C**: the pre-loop narrow
  pass derives `{applicable: true, args: "add 'x' … list", expected: "<the note
  appears>"}`, the adapter builds `python -m notes_cli <args>` via `run_smoke`,
  writes it back (deterministic on every later run), and verification #4
  **enforces** because `applicable=true`. The add→list round-trip the diagnosis
  identified as the real failure (`backend-redesign_arch.md:36-37`) now demotes a
  task that doesn't actually run — closing the 2% "agent never runs the
  deliverable" gap (`:38-40`) with teeth, not just a record. The
  `expected`-substring check (`plan_verify.py:242-243`, already merged) is what
  catches the false-green where the CLI exits 0 but lists nothing.
- **The SAME mechanism works for a Node CLI with only an adapter added.** A
  `NodeCliAdapter` (feature 5) ships `detect` (package.json),
  `run_smoke(args) -> ["node", bin, *args]`, and inherits the **identical**
  `acceptance_spec` precedence + the **identical** `AcceptanceSpec` return. The
  same narrow pass (args-only schema, language-neutral applicability judgment)
  derives a Node spec; the same run-loop branch (`spec.applicable` → demote/record)
  enforces it. **Zero run-loop edit** — the generality proof the parent note
  demands (`backend-redesign_arch.md:177,203-205`). The run-loop never learns
  that `node` exists; the adapter owns every language string.

This is the concrete discharge of constraint 1: the only python-shaped code in
the whole feature lives inside `PythonCliAdapter`; the derivation, the
applicability gate, the write-back, and the execution path are all
language-agnostic.

---

## What this note does NOT cover (deferred)

- **Self-fix route-back** (feature 3, `feat/acceptance-self-fix-loop`): feeding
  the run-smoke failure output back into `code_with_retry`. This feature now
  *demotes* on an applicable failure and persists the reason
  (`plan_verify.py:275-310` already stores command/verdict/reason); feature 3
  consumes that signal to retry. No retry loop is added here.
- **`NodeCliAdapter` / second-language adapter** (feature 5,
  `feat/node-cli-adapter`): the spec shape + run-loop branch are *designed* to
  pick it up with no run-loop edit (resolution 5), but feature 5 ships the
  subclass + its tests (the language-agnosticism lock).
- **Further `agent.py` decomposition** (parent migration item 6, opportunistic).
- **The `docs/architecture.md` / `docs/threat-model.md` updates** — the normal
  post-coding "Docs to update" handoff: a new Architectural decision row
  (acceptance gate is now enforcing behind an applicability signal), File-layout
  entries if a module is added, the T11→resolved + T12/SC7 threat-model changes
  (resolution 4), and the v0.14 `notes_cli` 3/3 outcome-gate note. **Specified
  here, authored by the doc-owner spawn**, not in this design note (parent note,
  last bullet, `backend-redesign_arch.md:365-367`).

## Acceptance criterion of the feature itself

**notes_cli 3/3 consistent `task_solved` via the enforcing derived path** — the
v0.14 outcome gate (parent note §Goal; `docs/architecture.md` "outcome-driven
release gate"). The feature's plan should carry the Product Contract
`## Must not break`: *(a)* a project with NO applicable acceptance spec (a Python
library) must NOT be failed by verification #4 — the feature-2 regression must
not return; *(b)* a `done` task WITH an applicable spec means the spec passed —
no regression to record-only "done". Both halves are the discriminator's two
failure modes; both must be tested (a library stays green/observational, a
non-running CLI demotes).

---

## Timing fix (post-probe)

> Added after the 3-run live `notes_cli` probe on `feat/acceptance-spec-in-tasks`
> @ `caa564f` (fixture `notes_cli_empty` = greenfield/empty). The original note
> (resolutions 1-5) is correct about *where* applicability lives and *how* the
> spec is built; it got the **timing** wrong. This section corrects that one axis
> and is additive — the `AcceptanceSpec` shape, the args-only constraint, the
> adapter-owns-argv seam, and the library-no-regression lock all stand
> unchanged. Only **when** applicability is judged and **when** enforcement
> engages move.

### What the probe exposed (evidence)

Three runs, scores 7,7,4 — never 3/3 `task_solved` (the v0.14 goal). The
mechanical checker's own `acceptance` criterion was **True at end of run**
("CLI работает: add→list через app.py") — the deliverable *did* work — yet the
gate scored it as if it hadn't, because **the gate never engaged**:

- The pre-loop derivation card read `T001..T007: observed (no runnable CLI)` —
  i.e. `_derive_specs_for_tasks` (`plan_loading.py:330`) wrote
  `applicable: false` for **every** task.
- The acceptance card then read `Acceptance run-smoke skipped (pkg-unresolvable)`.
- Net: verification #4 was observational throughout (resolution 1's A-path),
  exactly as designed for a library — but `notes_cli` is **not** a library, it
  is a greenfield CLI build.

### Root cause — applicability is judged against an empty filesystem

`_derive_acceptance` runs **pre-loop** (`plan_loading.py:115-118`,
`_pre_loop_passes`), before any task executes. On a greenfield fixture the repo
is empty: no package, no `__main__.py`, nothing `resolve_pkg` can bind. Two
distinct failure modes compound, and they are NOT the same defect:

1. **Intent vs. state conflation in the derivation.** The prompt
   (`prompts/derive_acceptance.md`) asks Q1 "**Is there** a runnable
   command-line deliverable here?" The present-tense "is there" invites a
   *filesystem* reading. On an empty repo the honest answer to "is there a
   runnable CLI" is *no* — so the model returned `applicable: false`, and that
   `false` was **persisted as a derived marker**. Because
   `acceptance_needs_derivation` (`base.py:128-138`) skips any *decodable*
   marker forever, the not-applicable verdict is **permanent for the whole run
   and every resume** — enforcement is structurally disabled before the CLI is
   ever built. This is the dominant failure mode the probe hit.
2. **Per-task enforcement timing.** Even with intent correctly `true` for the
   CLI, `_verify_acceptance` runs **per task** (`plan_runner.py:263` →
   `plan_verify.py:90`). An early task (`T001 create package skeleton`) cannot
   run add→list yet — the deliverable legitimately isn't built. A per-task
   enforcing gate would demote that early task as a false-negative. The original
   note never addressed "applicable-but-not-built-yet"; it assumed applicability
   alone is sufficient to enforce. It is not — you also need *"should be
   runnable **by now**"*.

The crux the spawn names: **"no runnable entrypoint" is the same observable for
(a) an early greenfield task, (b) a finished library by design, and (c) a CLI
that should run but is broken** (the diagnosed `__main__.py` coin-flip). The
fix must demote (c) without false-demoting (a) or (b). Filesystem state alone
cannot tell them apart — only *intent × position-in-plan × filesystem* can.

### The three signals and what each can answer

| Signal | Source | Derivable on empty repo? | Answers |
|---|---|---|---|
| **Intent** — "is this *meant* to be a runnable CLI deliverable?" | plan / task TEXT | **Yes** (pure text) | (b) library vs CLI |
| **Position** — "has the plan reached the point where it *should* run?" | task index / a wiring marker | Yes (plan structure) | (a) not-built-yet vs should-run |
| **State** — "does it actually run now?" | filesystem + run-smoke | No (needs files) | (c) should-run-but-broken |

The original design collapsed Intent and State into one pre-loop LLM judgment.
The fix **separates them**: judge Intent pre-loop (text-only, deterministic
write-back), check State at verify-time (deterministic run-smoke, no LLM), and
gate enforcement on Intent **AND** Position so an early greenfield task is
observed, not demoted.

### Decisions (options → recommendation)

#### Q1 — WHEN to evaluate applicability + enforce

**Recommendation: 1(a) — split intent (pre-loop, text-only) from enforcement
(verify-time, filesystem), and gate enforcement on a position signal.** This is
candidate (a) from the spawn, sharpened with (c)'s "enforce only at the point
the deliverable should be runnable end-to-end".

The decisive change is to **re-scope the derivation prompt from STATE to
INTENT**. Q1 becomes "is this task's deliverable *meant to be* a runnable
command-line program?" — answerable from task text on an empty repo, and
**stable** across the whole build (it does not flip from false→true as files
appear). notes_cli's tasks describe building a CLI with add/list/search/delete →
intent `applicable: true`, derivable at task 0.

Enforcement (the actual run-smoke + demote) stays at verify-time
(`_verify_acceptance`) where files exist — but only **demotes** when three
conditions hold together:

```
enforce = spec.applicable          # intent says "this is a CLI deliverable" (pre-loop, text)
          AND should_run_now(task) # position says "the plan has reached runnability"
          AND not run_smoke_ok     # state says "it does not actually run" (verify-time, deterministic)
```

When `spec.applicable` but NOT `should_run_now` → **observe** (record + card,
no demote): the early-greenfield case (a). When NOT `spec.applicable` →
**observe**: the library case (b), unchanged from feature 2. Only the
should-run-now-but-broken case (c) demotes.

- **Rejected 1(b) — single end-of-plan acceptance check.** Tempting (it
  naturally sidesteps "not built yet" by only checking at the end) but it loses
  per-task attribution: a 7-task plan that fails add→list at the end can't say
  *which* task broke it, and feature 3's self-fix route-back keys off a per-task
  failure signal (`plan_verify.py` records per-task command/verdict/reason). It
  also can't demote the specific `done` task whose job was to wire the
  entrypoint. Keep per-task, gate on position.
- **Rejected 1(c) as stated — per-task derivation at verify-time.** Re-deriving
  intent per task at verify-time would add an LLM call per task-completion
  (Q3 forbids) and re-inject per-run nondeterminism into the gate (the exact
  con resolution 3 closed by writing intent back once). We keep 1(c)'s good
  half — "enforce only on the task(s) where the deliverable should now be
  runnable end-to-end" — via the deterministic `should_run_now` position signal,
  with **no** per-task LLM call.

#### Q2 — HOW to distinguish should-run-but-broken (demote) from not-built-yet / library (observe)

**Recommendation: the position signal `should_run_now(task)` is the new
discriminator that flips an *applicable-intent* task from observe to enforce.**
Where the signal lives, in precedence order:

1. **The end-of-plan boundary (zero new model input, recommended baseline).** A
   task is `should_run_now` when it is the **last not-done task in the plan** (or
   the plan is on its final task). Rationale: by the last task an
   applicable-intent project should be runnable end-to-end; earlier tasks may
   not be. This is a pure plan-structure computation (`idx == last
   not-done index`), available in `plan_runner.run_plan_inner` where
   `enumerate(live_tasks)` already gives `idx`. Deterministic, no LLM, no
   filesystem guess. It directly answers the spawn's "(e.g. only when an
   applicable-intent project has reached a point where it SHOULD be runnable —
   last task)". For notes_cli (a single wired deliverable built across tasks)
   this enforces add→list exactly once, at the end, where the diagnosed
   coin-flip (`__main__.py` present or not) is decided.
2. **An optional intent-carried `runnable` / wiring marker (forward, not
   required for the fix).** The pre-loop derivation already returns a per-task
   judgment; it can additionally mark the task that *wires the entrypoint* (the
   one whose Files include `__main__.py` / the console-script) as the
   runnability point. This is a refinement of (1) for multi-deliverable plans;
   the last-task baseline is sufficient for notes_cli and every single-deliverable
   build, so ship (1) and leave (2) as a documented extension. **Both are
   text/structure derivable on an empty repo** — neither needs files.

Crucially, **State (run-smoke) is consulted ONLY when Intent AND Position both
say "this should run now".** So:
- Early greenfield task (a): Intent=true, Position=false → run-smoke is **not
  run as a gate** (may still be recorded observationally) → never demotes.
- Library (b): Intent=false → never reaches Position/State → observes. The
  feature-2 / resolution-1 floor-never-applicable lock is **untouched**.
- Should-run-but-broken (c): Intent=true, Position=true, run-smoke fails →
  **demote**. This is the case that scored 4 in the probe and must turn into a
  real failure signal so the model is forced to produce a runnable CLI (and,
  with feature 3, repair it) to reach `task_solved`.

The signal that flips "not runnable" from *ok, observe* to *fail, demote* is
therefore: **`spec.applicable` (intent, persisted) AND `should_run_now` (position,
computed in the run-loop) — at which point a failing run-smoke (state) demotes.**

#### Q3 — cost / UX (no per-task LLM call at verify-time)

**Recommendation: intent is derived ONCE pre-loop (cheap, text-only,
write-back), and only the deterministic run-smoke is (re-)attempted at
verify-time. Zero per-task LLM call at verify-time.** This is already the
structure resolution 3 built (`_derive_acceptance` pre-loop + marker write-back);
the fix changes *what the one pre-loop pass judges* (intent, not state), not
*how often* it runs. `should_run_now` is a plan-index comparison — no model, no
I/O. run-smoke at verify-time is the existing deterministic `execute()` path
(`plan_verify.py:258-266`). So the per-run LLM budget is **unchanged**: one
derivation pass per un-marked task, pre-loop, exactly as today.

One UX note: the pre-loop card must stop reading `observed (no runnable CLI)`
for an intent-applicable task. With the intent re-scope it reads e.g.
`T00N: runnable CLI (enforced at final task)` for applicable tasks and
`observed (library / no CLI)` only for genuinely non-CLI ones — so the operator
can see at plan-start that enforcement *will* engage, and where.

#### Q4 — invariants preserved

All four hold unchanged — the fix touches timing, not the seams the invariants
live on:

- **Args-only.** The model still emits `{applicable, args, expected}` (now with
  `applicable` meaning *intent*); the adapter still builds argv via
  `run_smoke(args)`. No model-emitted shell. Untouched.
- **Generality (no language string in the run-loop).** `should_run_now` is a
  plan-index predicate — pure structure, zero language knowledge. The run-loop
  still reads `spec.applicable` from the adapter and now ANDs it with a
  structural bool it computes itself. `NodeCliAdapter` plugs in with no run-loop
  edit (resolution 5 still holds — the position gate is language-neutral).
- **Library no-regression.** Intent=false for a real library is **more** robust
  under the re-scope, not less: an importable library is "not meant to be a
  runnable CLI" regardless of build state, so the text-only judgment is stable
  and the floor-never-applicable lock is intact. The Must-not-break test (a)
  stands.
- **PM "plumbing / observational where not applicable" stance.** Preserved and
  *extended*: not-applicable observes (as before), AND applicable-but-not-yet-at-
  runnability observes (new) — enforcement is now strictly the should-run-but-
  broken case, the narrowest possible demoting surface.

### Confirmation against the probe

With this design the greenfield `notes_cli` run:
1. Pre-loop: derivation judges **intent** from task text → `applicable: true` for
   the CLI tasks (the build of add/list/search/delete is plainly a runnable CLI),
   persisted as a derived marker — deterministic on resume.
2. Tasks 1..N-1: Intent=true but Position=false (not the last task) → run-smoke
   observed, **never demotes** — the early-not-built-yet case is safe.
3. Final task: Intent=true AND Position=true → run-smoke `python -m notes_cli
   add … list` runs at verify-time. If the model produced a runnable CLI
   (the `__main__.py` is wired and add→list round-trips, matching `expected`) →
   **passed**, task stays done → contributes to **3/3**. If the model produced
   the GAVE_UP variant (no `__main__.py`) → run-smoke fails → **demote
   done→failed** → the gate now has teeth exactly where the probe showed it had
   none. A library or a non-CLI plan never reaches step 3's demote (Intent=false).

So the gate **will enforce** on greenfield notes_cli and can reach 3/3 once the
model emits a runnable CLI, while never false-demoting a library (b) or an early
task (a). The 7,7,4 outcome was the gate failing to engage; this engages it at
the one correct point.

### Concrete seam changes (what differs from current implementation)

1. **`prompts/derive_acceptance.md` — re-scope Q1 from STATE to INTENT.**
   Change Q1 from "**Is there** a runnable command-line deliverable here?" to
   "**Is this task's deliverable meant to be** a runnable command-line program?"
   (intent, present-or-future, text-derivable on an empty repo). Add an explicit
   line: *"Judge the task's intent from its description — do NOT assume the code
   exists yet; a from-scratch build of a CLI is still `applicable: true`."* This
   is the single change that fixes the dominant failure mode (the permanent
   `applicable: false` write-back on greenfield). `args`/`expected` Q2/Q3 are
   unchanged. The marker semantics (`encode_derived_acceptance`,
   `base.py:87`) are unchanged — `applicable` now carries *intent*, same field,
   same persistence.

2. **`plan_runner.py` (`run_plan_inner`, the `enumerate(live_tasks)` loop,
   ~`:142`) — compute and pass a `should_run_now` position signal into
   `verify_task`.** Baseline: `should_run_now = (idx == last_not_done_index)`
   (or equivalently "this is the final remaining task"). Pass it through
   `verify_task(... , should_run_now=...)` at `:263`. Pure structure, no LLM, no
   I/O. (Threaded as a new keyword arg — the verify call site is the only
   caller.)

3. **`plan_verify.py` (`verify_task` / `_verify_acceptance`, `:60-169`) — gate
   demotion on `applicable AND should_run_now`, not `applicable` alone.** The
   demotion branch at `:167` becomes
   `if spec.applicable and should_run_now and not ok: return _demote(outcome)`.
   When `applicable and not should_run_now`, the run-smoke result is still
   **recorded + carded observationally** (so the operator sees progress and
   feature 3 has a per-task trail) but never demotes — the not-built-yet case.
   `_verify_acceptance` takes the new `should_run_now: bool` param threaded from
   `verify_task`. The `assert not applicable` noop invariant (`:161`) is
   unaffected (a noop still never demotes regardless of position).

4. **`plan_loading.py` (`_derive_specs_for_tasks`, `:330`) — fix the card
   wording** so an applicable task no longer prints `observed (no runnable
   CLI)`. With the intent re-scope the verdict line becomes
   `"runnable CLI (enforced at final task)"` for `applicable=true` and
   `"observed (library / not a CLI)"` for `applicable=false`. No logic change
   beyond the string — but it is load-bearing for operator trust (the probe's
   misleading card is what masked the bug).

5. **`python_cli_adapter.acceptance_spec` / `acceptance_applicable`
   (`:125-165`) — NO change.** The adapter still reads the persisted
   `applicable` from the marker and builds the spec; it has no knowledge of
   position (correctly — position is plan structure, not adapter concern). The
   `applicable` bool it returns now means *intent*; the run-loop ANDs it with
   `should_run_now`. This keeps the adapter language-agnostic and the generality
   proof (resolution 5) intact.

**Net:** one prompt re-scope (the actual root-cause fix), one new structural
bool computed in the run-loop and threaded through `verify_task`, one
demotion-condition AND, and one card-string fix. No new LLM pass, no per-task
verify-time derivation, no adapter change, no new language string in the loop.
The original note's resolutions 1-5 stand; this section corrects only the
intent-vs-state timing they conflated.

### What this section does NOT change

- The `AcceptanceSpec` dataclass, args-only schema, write-back-once discipline,
  and the SC1/SC2/SC3 execution boundary (resolutions 2-4) — all unchanged.
- The feature's own acceptance criterion and Must-not-break contract
  (§"Acceptance criterion of the feature itself") — unchanged, and now actually
  reachable on greenfield. Add one Must-not-break case from this section: *(c)*
  an **early** task of an applicable-intent greenfield plan must NOT be demoted
  before the plan reaches runnability (the not-built-yet false-demote), tested
  alongside the existing library (a) and broken-CLI (b/demote) cases.
