# acceptance-spec-in-tasks — plan

Decision authority: autonomous   # per-feature override — PM "на автомате" / "продолжай как считаешь нужным"

Source: backend redesign migration step 4, `.ai-pm/arch/backend-redesign_arch.md` (Fork 2 "B contract / C fallback / A floor"); PM-greenlit as the next feature. Integration design: `.ai-pm/arch/acceptance-spec-in-tasks_arch.md`. Security posture (model-derived checks are **args-only**) and the **generality** constraint (this is NOT a notes_cli-specific solution) are explicit PM decisions — see Key design decisions.

This feature gives the **observational** acceptance gate (shipped by feature 2, PR #169) its **teeth**: verification #4 flips from record-only to **enforcing** (demote `done → failed`) — but ONLY where an *applicable* acceptance expectation exists, so projects that have none (libraries) are never wrongly failed. It also adds the precise per-task acceptance spec (task-declared) and a constrained model-derived fallback, beyond feature 2's bare default-floor.

## Key design decisions

- **KD1 — Generality is a first-class constraint (PM).** This is the language-agnostic acceptance mechanism, debugged on python-cli, NOT a notes_cli/python special case. The **run-loop carries zero language strings**: it asks the `detect()`-selected adapter for an `AcceptanceSpec`, runs `spec.command`, and branches on `spec.applicable`. Every "how to run this deliverable" string is assembled inside the adapter (`run_smoke(args)`). A future `NodeCliAdapter` (feature 5) plugs in with **no run-loop edit**. (Source: parent arch note's language-agnostic thesis.)
- **KD2 — Enforcement gates on `spec.applicable` (the CLI-vs-library discriminator).** The gate **enforces** (demote) iff an *applicable* spec exists — task-declared (B) or narrow-pass-derived-and-marked-applicable (C). It stays **observational** (record-only, feature-2 behavior) when only the default-floor (A) applies or the derivation returns `applicable: false` (a library: "no runnable CLI deliverable"). **The default-floor never sets `applicable: true`** — the structural lock that prevents feature 2's library regression from returning.
- **KD3 — Model-derived checks are ARGS-ONLY (PM security decision).** When a task declares no acceptance, a narrow pass derives one, but the model may return ONLY `{applicable, args, expected}` — never free-form shell. The **adapter** builds the run argv from `args` (python-cli → `python -m <pkg> <args>`). The model cannot inject arbitrary commands. Execution stays through the existing gated `execute()` path (policy hard-blocks SC2, bwrap SC3, cwd-pinned, `trust="yolo"` as a plan-owned check). Human task-declared acceptance is trusted (like the existing `Test command:` field that already runs at yolo) but routes through the adapter as args too, so the verb is always code-owned. (Resolves the T11 forward-flag.)
- **KD4 — `AcceptanceSpec` dataclass replaces the `(command, expected)` tuple.** `AcceptanceSpec(command, expected, applicable, source)` — applicability cannot ride a 2-tuple without the run-loop inferring it (which would re-inject language knowledge into the loop). (Arch note overrule of the tuple.)
- **KD5 — Derivation runs pre-loop and writes back.** The narrow pass runs once per task lacking a declared acceptance (beside the existing skill-annotation pre-pass), and the result is **written back** into the task so the next run is deterministic (no re-derivation). Write-back targets the JSON-canonical task representation (round-trips via `task_from_json`); the in-loop tasks tuple is returned typed (avoids the `parse_tasks_md` `Acceptance:` round-trip drop — feature-2 review finding 7). (Source: `plan_loading._annotate_plan` write-back+re-hash pattern.)
- **KD6 — spike not needed.** The `python -m <pkg>` runnability idiom is execution-verified (feature 1 `test_scaffold_smoke`); the `narrow_pass` json_schema idiom is established (skill-annotator / fork resolution). No new hinge idiom.
- **Residual security risk (surfaced, accepted under KD3):** even args-only, the derived *args* reach a yolo shell, and `bwrap` degrades to policy-only on restricted-userns hosts. Mitigated by: args-only (no free-form shell), the bwrap sandbox where available, cwd-pinned + policy hard-blocks, and pre-run surfacing of the acceptance command (the user sees what will run). Recorded in the threat-model update.

## Scenarios

1. When a task **declares** an acceptance expectation and its project has an acceptance adapter, `run_plan` runs the adapter-built acceptance command; the task is `done` only if it passes (exit 0 and, when an expected observable is given, that observable appears in the output) — otherwise demoted `done → failed`. The gate now has teeth.
2. When a task **does not declare** an acceptance expectation, a narrow pass derives one (args-only); if the derivation marks it **applicable**, the spec is written back and the gate **enforces** it (as scenario 1) on this and every later run.
3. When the derivation marks the task **not applicable** (e.g. a python **library** with no runnable CLI deliverable), or only the bare default-floor applies, the acceptance run-smoke is **recorded + surfaced but the task is NOT demoted** — feature 2's observational behavior, preserving every existing `/go` flow (no library regression). This is the load-bearing no-regression invariant.
4. A derived spec is **written back** into the task, so a subsequent run uses the recorded spec deterministically instead of re-deriving (no per-run nondeterminism in the gate).
5. A model-derived check is **args-only**: the executed command is the adapter's code-owned argv (`python -m <pkg> <args>`) with only the subcommand args model-supplied; the model can never inject arbitrary shell. It runs through the existing sandboxed/policy-gated path.
6. The **run-loop is language-agnostic**: it enforces through any `provides_acceptance` adapter via `AcceptanceSpec` with no python-specific code; the same path would enforce for a Node CLI given only a Node adapter (feature 5).
7. A non-empty `expected` observable must appear in the run-smoke output for a `passed` verdict (a deliverable that exits 0 but produces the wrong/empty output is caught — not a false-green).
8. **notes_cli reaches 3/3 `task_solved`** via the derived (args-only) path (it has no human-declared acceptance) — the v0.14 outcome gate, now with teeth.

### Failure paths (feature touches external I/O — LLM call + subprocess + plan file write-back)

9. When the narrow-pass derivation **fails** (LLM error, timeout, invalid/non-conforming JSON), the task falls back to the **default-floor (observational, not applicable)** — no crash, no fabricated enforcement, no demotion. A failed derivation never invents an enforcing spec.
10. When the **write-back fails** (disk error), the derived spec is used in-memory for this run and the failure is logged; the next run re-derives. No crash, no partial/corrupt TASKS file.
11. When an **applicable** acceptance command **times out or exits non-zero**, the task is demoted `done → failed` with the reason recorded (`timeout` / `exit N` / `expected-missing`); timeout comes from existing config (no magic number).
12. When `resolve_pkg` (or the adapter's argv assembly) **raises** for an *applicable* spec, the task is `failed` with reason `pkg-unresolvable`; for a *not-applicable* task the same condition is **observational** (no demotion) — the applicability flag, not the error, decides enforcement.

## Existing behaviors this feature touches

(from `docs/user-journeys.md` Journey 5 + `docs/architecture.md` `### Task outcome status` / `## State model` / `### System invariants` + the `run-plan` contract + feature 2)

- **Feature 2's observational behavior must be preserved for no-applicable-spec projects** — libraries and unsupported types are never demoted by this check (the no-regression invariant; scenario 3).
- **The existing three machine checks** (Files / Test-cmd / HEAD) and their `done → failed` demotion are unchanged; acceptance enforcement is the 4th, gated on `applicable`.
- **`done | failed | skipped` taxonomy unchanged** — no new status; enforcement reuses the existing `done → failed` demotion (the edge that was inert in feature 2 now fires where applicable).
- **The skill-annotation pre-loop pass** gains a sibling (acceptance derivation); plan re-hash / `plan_modified` detection after write-back must be preserved exactly (mirror `_annotate_plan`).
- **`Test command:` at `trust="yolo"`** — the precedent this feature's acceptance execution follows; unchanged.
- **The merged `acceptance_spec`/`run_smoke`/`acceptance_adapter`/`AgentState` plumbing** (feature 2) — extended, not replaced; `acceptance_spec` return type changes tuple→`AcceptanceSpec` (all current call sites updated).
- **All existing tests must pass** — esp. the feature-2 acceptance suite (now updated where it asserted "never demotes" for applicable specs) and the run_plan suite.

## Contracts

- `AcceptanceSpec(command: str, expected: str, applicable: bool, source: str)` — frozen dataclass. `command` is the adapter-built argv-string; `expected` is the observable substring (`""` = exit-0-only); `applicable` gates enforcement; `source` ∈ {`declared`, `derived`, `floor`} for surfacing/metrics.
- `Skill.acceptance_spec(self, task) -> AcceptanceSpec | None` — return type change (was `tuple | None`); default `None`. Adapter precedence: task-declared (B) → derived-and-written (C) → default-floor (A, `applicable=False`).
- Adapter builds the run command from args generically via the existing `run_smoke(args)` — no new per-language run-loop code.
- **Acceptance derivation** — a `NarrowPass` with `output_schema = {applicable: bool, args: string, expected: string}` (sampler-enforced JSON); run pre-loop for each task with no declared acceptance; result written back into the task's acceptance representation (round-trippable; encodes applicable+args+expected so it is not re-derived).
- **`run_plan` verification #4 (now enforcing where applicable)** — get `acceptance_spec(task)`; if `spec.applicable`: run `spec.command` via the existing `execute(..., trust="yolo", sandbox=…, shell_exec_timeout=…)`, demote `done → failed` on failure (exit≠0 / timeout / expected-missing / argv-assembly error), record verdict+reason+source. If not applicable: record (observational), never demote (feature-2 behavior). Surface the card either way.

## Stack expectations touched

(from `docs/stack-notes.md`)
- **narrow_pass / structured output**: "`output_schema` … the model is guaranteed to emit valid JSON conforming to the schema" — the derivation uses sampler-enforced JSON (`{applicable,args,expected}`), not prompt-begging. Source: `code_scalpel/narrow_pass.py` docstring; LM Studio `response_format=json_schema`.
- **subprocess**: argv list, no shell; cwd pinned to project root. The acceptance command is built as an argv and dispatched through the existing `execute()` boundary; model-supplied args are tokenized, never a shell string. Source: https://docs.python.org/3/library/asyncio-subprocess.html#security-considerations ; SC2.
- **`python -m <pkg>`**: the python-cli adapter's argv; execution-verified (feature 1). Source: https://docs.python.org/3/library/__main__.html#main-py-in-python-packages
- **bwrap**: acceptance execution inherits the sandbox + degrade-on-userns-failure behavior from the shared `execute()` path. Source: https://github.com/containers/bubblewrap/issues/324 ; SC3.

## Interaction scenarios

Shared state: the per-task `PlanRunner` loop, `TASKS.{md,json}` (re-hashed each iteration), `STATE.json` (`AgentState`), the `SkillRegistry`, the trust level, TUI callbacks, and the LLM (the derivation is an LLM call).

- **When the acceptance derivation writes a spec back into the plan:** the plan re-hash / `plan_modified` detection must treat the write-back as the loop's own edit (mirror `_annotate_plan`), NOT a user mid-run edit — otherwise the loop would stop with `plan_modified` on its own write.
- **When both the skill-annotation pre-pass and the acceptance-derivation pre-pass run:** they compose without clobbering each other's write-backs (ordering defined; each re-hashes after its own write).
- **When a task is resumed after a crash:** a previously written-back derived spec is read from the plan (not re-derived); the persisted run-smoke verdict/source is available.
- **When the project trust is `skeptic`:** the acceptance command still runs at `trust="yolo"` (plan-owned check), and because the command is adapter-built args-only, no untrusted free-form string reaches the shell.
- **When enforcement demotes a task (feature 3 not built):** the recorded failure verdict + reason is the exact signal `feat/acceptance-self-fix-loop` will later consume to route back to `code_with_retry` — this feature must produce that signal cleanly (but does NOT route back).

## Test plan

- Existing tests that must pass: **all existing tests** — esp. the feature-2 acceptance suite in `tests/test_acceptance_gate.py` (updated where it asserted "never demotes" — now: never demotes when NOT applicable; demotes when applicable) and the `run_plan` suite.
- New tests:
  - `test_enforce_demotes_when_declared_acceptance_fails`: a task with a declared acceptance whose command fails → demoted `done → failed`.
  - `test_enforce_keeps_done_when_declared_acceptance_passes`: declared acceptance passes (exit 0 + expected present) → stays `done`.
  - `test_enforce_on_derived_applicable_spec`: task with no declared acceptance, derivation returns `applicable:true` → spec used + written back + enforced (demote on failure).
  - `test_observational_when_derivation_not_applicable` (**no-regression, load-bearing**): derivation returns `applicable:false` (library) → recorded, task stays `done`, NOT demoted. Includes a real python-library shape (src-layout no `__main__.py`) to prove the feature-2 regression cannot return.
  - `test_floor_only_is_observational`: project with an adapter but no declared/derived applicable spec → default-floor recorded `applicable:false`, not demoted.
  - `test_derived_spec_written_back_not_rederived`: after derivation, the task's acceptance is persisted and a second run uses it without calling the LLM again (assert no second derivation pass).
  - `test_derived_command_is_args_only_adapter_built`: the executed command equals the adapter's argv built from the model's `args` (e.g. `python -m <pkg> add x`); a model `args` containing shell metacharacters does NOT produce a shell injection (tokenized; the command is code-owned argv).
  - `test_expected_observable_enforced`: non-empty `expected` absent from output → `failed` even on exit 0; present → `passed`.
  - `test_acceptance_spec_precedence`: declared (B) wins over derived (C) wins over floor (A); `source` reflects which.
  - `test_acceptance_spec_dataclass_shape`: `AcceptanceSpec` carries command/expected/applicable/source; `Skill.acceptance_spec` default returns `None`; `PythonCliAdapter` returns an `AcceptanceSpec`.
  - `test_derivation_failure_falls_back_observational` (**failure path 9**): narrow pass errors / returns non-conforming JSON → default-floor, `applicable:false`, no demotion, no crash.
  - `test_writeback_failure_uses_inmemory_and_logs` (**failure path 10**): write-back disk error → spec used this run, no crash, plan file not corrupted.
  - `test_applicable_pkg_unresolvable_demotes_vs_notapplicable_observes` (**failure path 12**): `resolve_pkg` raises → applicable spec demotes (`pkg-unresolvable`); not-applicable task observes (no demote).
- Generality test (**guards against notes_cli/python overfit — PM constraint**):
  - `test_run_loop_enforces_through_a_nonpython_adapter`: a fake `provides_acceptance` adapter (no python) returning an `AcceptanceSpec(applicable=true)` → the run-loop enforces (demotes on failure) through it with **zero python-specific code** in the loop path. Proves the mechanism is adapter-generic.
- Interaction scenario tests:
  - `test_writeback_not_flagged_as_plan_modified`: the derivation write-back does not trip the `plan_modified` stop (loop's own edit, re-hashed).
  - `test_annotation_and_derivation_compose`: both pre-passes run without clobbering each other's write-backs.
  - `test_derived_spec_resumes_from_plan`: a resumed run reads the written-back spec instead of re-deriving.
  - `test_acceptance_runs_at_yolo_on_skeptic_project`: enforcement executes the adapter-built args-only command at yolo on a skeptic project.
- Stack-spec tests (cite source URL in a comment; verify the rule):
  - `test_derivation_uses_json_schema_structured_output`: the derivation pass is configured with `output_schema` (sampler-enforced), not prompt-parsed (cites narrow_pass / LM Studio json_schema).
  - `test_acceptance_command_argv_no_shell`: the acceptance command is argv-built; model args with metacharacters do not reach a shell (cites asyncio-subprocess security URL).
- Test-wiring-parity: `test_enforce_on_derived_applicable_spec` and the generality test drive the **production** `PlanRunner`/registry/`acceptance_adapter` path, not a hand-built setup.
- **Feature acceptance criterion (manual outcome probe, not a unit test):** `notes_cli` **3/3 `task_solved`** via the derived path — run the outcome probe N≥3 (Step 5.5 verify) before ship.

## Docs to update

- `docs/architecture.md`: Architectural decision — **Acceptance gate enforcement + per-task/derived acceptance specs (v0.14)**: `AcceptanceSpec` (applicable-gated enforcement), task-declared (B) / args-only narrow-pass-derived (C) / default-floor (A) precedence, the run-loop's language-agnostic contract (no language strings in the loop). Update `### Task outcome status` / `## State model` — the `done → failed` edge now fires on acceptance failure **where an applicable spec exists** (libraries/no-spec unaffected). Update `### Outcome-driven release gate` — `notes_cli` 3/3 now the live teeth.
- `docs/user-journeys.md`: Journey 5 — a `done` task whose project has an acceptance expectation now means the deliverable actually worked; tasks/projects without one are unaffected (no false failures).
- `docs/threat-model.md`: resolve the T11 forward-flag — model-derived acceptance is **args-only** (constrained, cannot be free-form shell), executed through the existing sandboxed/policy-gated yolo path; record the residual risk (args reach yolo shell; bwrap degrade) + mitigations. Add/adjust the relevant Threat row (T11 → resolved; new row/SC if warranted). Update `Last reviewed`.
- `docs/plan.md`: v0.14 progress ✓ — the acceptance gate now enforces (teeth); `notes_cli` 3/3 is the live release signal.
- `.ai-pm/contracts/run-plan.md`: `## Must not break` — a `done` task means the deliverable's acceptance passed **where an applicable acceptance spec exists**; tasks/projects with no applicable spec are unaffected (libraries never wrongly failed). `## Acceptance checks` — `notes_cli` N≥3 is the enforced release gate.

## Out of scope

- **Self-fix route-back on acceptance failure** (route the run-smoke output back to `code_with_retry` and iterate) — `feat/acceptance-self-fix-loop` (feature 3). This feature produces the failure *signal* cleanly but does not act on it; a demoted task simply stays `failed`.
- **`NodeCliAdapter` / other-language adapters** — `feat/node-cli-adapter` (feature 5). The mechanism here is built to **allow** them with no run-loop edit (KD1, proven by `test_run_loop_enforces_through_a_nonpython_adapter`), but none is implemented.
- **Free-form model-proposed commands** — explicitly rejected by the PM security decision (args-only). Sibling of "how much to trust a model-derived check": full-command and human-only-checks were the considered alternatives; args-only chosen.
- **Enforcing where no applicable spec exists** — stays observational by design (the library no-regression lock). Sibling of the categorical choice "which tasks/projects the gate enforces on": all-python-projects (feature-2's rejected over-broad behavior) vs applicable-spec-only (chosen).
- **Automated CI wiring of the `notes_cli` N≥3 probe** — stays manual per the outcome-driven release-gate decision.
