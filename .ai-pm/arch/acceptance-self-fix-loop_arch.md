# Acceptance self-fix loop — design notes

## Context

Feature 3 of the backend redesign. After feature 4 (PR #170) the acceptance gate
(verification #4 in the run loop) demotes a task `done → failed` when three signals
agree: intent (`spec.applicable`), position (`should_run_now` = last not-done task),
and state (run-smoke fails) — see `code_scalpel/plan_verify.py` `_verify_acceptance`
(~140–193), demotion at ~186–192. Feature 3 turns that terminal demotion into a
bounded self-fix cycle: on an applicable + last-task run-smoke failure, route the
failing task back to `code_with_retry` with the run-smoke output as the failure
signal, re-verify, loop up to a budget, then finally `failed`. This makes the
project's "controlled autonomy = the model fails its own machine check and iterates"
promise literal (CLAUDE.md core principle; `docs/architecture.md` §"Machine checks
over prompt instructions") and is the consistency lever toward a stable `notes_cli`
3/3. The feature is explicitly deferred to here by the contract
(`.ai-pm/contracts/run-plan.md` Out-of-scope lines 90–92, Acceptance-checks 82–84).

PM decisions are fixed (ON by default, trust-gated, budget = 3) and are *not*
relitigated below — the note rules only on the two structural questions and the
invariant-preservation shape.

## Adjacent implementations

1. **`code_with_retry`** at `code_scalpel/agent.py` (~924–1002) — the build loop. Owns
   its OWN retry budget (`max_debug_attempts`, +1 initial), `seen_sigs` /
   `seen_file_sigs` no-progress guards, and the `pre_loop_snapshot` rollback. The
   layer that builds owns its retries. This is the home of `debug_pass` and the
   anti-loop guards Feature 3 must mirror.
2. **`debug_pass` + `_build_failure_retry_prompt`** at `agent.py` (~1960–2107) — runs on
   a *failed test attempt INSIDE* `code_with_retry`, before the next builder retry.
   Two anti-loop guards: (a) identical `test_output` two attempts in a row ⇒
   `should_break=True` ("the patch didn't change behaviour"); (b) repeated
   `hypothesis` ⇒ break. Self-fix wants the analogue of guard (a).
3. **`verify_task` / `_verify_acceptance`** at `plan_verify.py` (~67–193) — the pure
   Definition-of-Done reporter. Reads files / test-command / HEAD / run-smoke and
   returns `done` or `_demote(...)`. Drives NO code generation today.
4. **`auto_confirm(level)`** at `code_scalpel/policy.py` (~154–157) — already the machine
   trust gate: `return level in ("optimist", "yolo")`. The skeptic-no-autofix
   decision reuses this; no new trust logic needed.

## Behavioral risks in this area

`_run_task` (`plan_runner.py` ~257–300) already owns the only build→verify edge:
`code_with_retry(...)` then `verify_task(..., should_run_now=...)`. A self-fix loop
here re-feeds `code_with_retry` and re-calls `verify_task` — an **outer loop over the
same two calls**. The run-smoke executes shell at `trust="yolo"` through `execute()`
(`_run_smoke` ~282) regardless of agent trust; the trust GATE on auto-fixing is a
separate decision and must be enforced before re-entering `code_with_retry`, not
inside the smoke run. No new event subscriptions; no mutation feeds back into a
subscription (the cards are emitted, not consumed).

## Q1 — WHERE the self-fix loop is wired

### Variant A: inside `_verify_acceptance` / `verify_task` (plan_verify.py)
- **Where:** the verifier, on a would-be demotion, itself calls `code_with_retry`,
  re-runs smoke, loops, returns done/failed.
- **Relation to adjacent:** *asymmetric and inverted.* `plan_verify.py` is the pure
  "machine checks / Definition-of-Done" module (`docs/architecture.md` §"File layout
  (module map)"; module docstring: "the machine checks behind Definition-of-Done").
  It would acquire a dependency on the code-generation engine and become a builder.
- **Pros:** the loop sits exactly where the demotion decision lives; one call site.
- **Cons:** dependency-direction inversion — verify currently depends on nothing that
  builds; this makes the reporter drive the builder. Breaks the §"Narrow passes"
  separation. Trust + budget would have to thread into the verifier, widening its
  surface far past "report pass/fail".
- **Risks:** a future reader of `plan_verify.py` no longer trusts it as side-effect-free;
  the `_demote` purity ("preserve every field") gets entangled with rebuild state.

### Variant B: in `plan_runner.py` `_run_task` (RECOMMENDED)
- **Where:** the run loop, which already owns the build→verify sequence, orchestrates
  the cycle: build → verify → if acceptance-demoted AND trust permits AND budget left
  → rebuild with the run-smoke signal → re-verify → loop; finally `failed`.
- **Relation to adjacent:** *symmetric.* Mirrors `debug_pass` living inside
  `code_with_retry` — the layer that builds owns its retries; here the layer that
  *runs the plan* owns the build→verify retries. `verify_task` stays a pure reporter
  (returns done/failed only). Same dependency direction as today (runner → verify,
  runner → agent).
- **Pros:** keeps `plan_verify.py` pure; trust + budget live in the orchestration layer
  where the existing build retries already live; no new module dependency.
- **Cons:** `_run_task` grows (it is currently ~44 lines, well under the 300/50
  minimums — see "what the plan must honor" for the extraction note); trust + budget
  thread through one more call.
- **Risks:** the outer loop must re-snapshot / not double-count HEAD-advance checks;
  see the nesting note below.

**Recommendation: Variant B.** The decisive reason is dependency direction +
separation of concerns: `plan_verify.py` is the project's pure Definition-of-Done
reporter, and `docs/architecture.md` §"File layout (module map)" + the module's own
docstring make that purity load-bearing. The self-fix loop is a build-orchestration
concern, and the orchestration layer (`plan_runner._run_task`) already owns the one
build→verify edge — putting the loop there is exactly symmetric with `debug_pass`
nesting inside `code_with_retry`. A is rejected because it inverts the
reporter→builder dependency.

## Q2 — HOW the run-smoke failure signal reaches `code_with_retry`

Today `_record_acceptance` persists only a SUMMARY (`last_acceptance_command/verdict/
reason/source`); `_failure_reason` collapses the rich `ToolResult.output` to a compact
string ("exit N" / "timeout" / "expected-missing" / "refused"). The model needs the
actual run-smoke stdout/stderr to fix the bug.

### Variant A: thread the output inline (RECOMMENDED)
- `verify_task` / `_verify_acceptance` returns (or attaches to the `TaskOutcome`) the
  failing run-smoke `ToolResult.output`, so `_run_task` hands it straight to
  `code_with_retry` in the same invocation. No new persisted state.
- **Resume semantics:** the self-fix happens in the *same* `_run_task` call
  immediately after verify. If the process dies mid-self-fix, resume sees
  `current_task` still populated + `step_phase` (see `_persist_task_start`,
  `plan_runner.py` ~243–255) and `last_acceptance_verdict="failed"` — it offers
  "Continue / Restart T00N" and re-derives the spec + re-runs smoke from scratch on
  resume. The stdout was a *within-turn* signal, not cross-turn state; nothing is
  lost that resume can't regenerate.
- **Pro:** persistence is for cross-turn resume; this signal is consumed in-turn.
  Persisting full stdout would bloat `STATE.json` (run-smoke output is unbounded;
  the existing summary fields are deliberately compact).

### Variant B: persist a new `last_acceptance_output` field on AgentState
- **Con:** unbounded write into `STATE.json` per failing task; resume gains nothing it
  can't regenerate; widens the state schema for a within-turn value. Only worth it if
  self-fix were to span turns — it does not.

**Recommendation: Variant A (inline).** Attach the failing `ToolResult.output` to the
returned `TaskOutcome` (a new optional field, defaulting `None`, preserved by
`_demote`'s `dataclasses.replace`) so `verify_task` stays a pure reporter that merely
*reports more* — it does not gain a builder dependency (keeps Q1-B intact). Do NOT
persist it.

## Invariants preserved (checklist — cite, do not weaken)

- **Language-agnostic run loop** (`docs/architecture.md` §"ProjectAdapter" / KD1
  generality; feature 1/2 contract): the self-fix path carries ZERO language strings.
  The run-smoke command comes only from the `detect()`-selected adapter
  (`spec.command`); the retry prompt the builder gets is assembled from
  adapter-provided command + the run-smoke `ToolResult.output` — no `python` / `-m` /
  `notes_cli` literals anywhere in `plan_runner` or the self-fix path. `notes_cli` is
  the proof, not the target.
- **Mirror `debug_pass` shape** (`docs/architecture.md` §"Narrow passes", §"Machine
  checks over prompt instructions"): bounded retries + a minimal anti-loop guard —
  see the dedicated section below.
- **Trust gate is a machine check, not a prompt** (§"Machine checks over prompt
  instructions", §"Fork delegation by trust level"): the skeptic-no-autofix decision
  is enforced in code by reading the trust level — reuse `policy.auto_confirm(level)`
  (already `optimist`/`yolo` ⇒ True). NEVER "the prompt asks the model not to". At
  `skeptic` the loop records `failed` and stops, exactly as today.
- **Taxonomy unchanged** (§"Behavioral contract" / §"Task outcome status"): no new
  task-outcome status. Self-fix reuses the existing `done → failed` edge, just
  *deferred* until the budget is exhausted. The new `TaskOutcome` field carries the
  failure signal, not a new status value.
- **No magic numbers** (§"Architectural constraints" — everything in config): budget
  (default 3), the on/off knob (default ON), and any self-fix prompt temperature live
  in `config.py` `AgentConfig` (pydantic), alongside `max_debug_attempts` /
  `debug_pass_*`.

## Anti-loop guards (recommend the minimal machine guards)

`code_with_retry` and `debug_pass` already carry deep anti-loop state INSIDE each
build attempt (`seen_sigs`, `seen_file_sigs`, `seen_hypotheses`, identical-output
break). The OUTER self-fix loop needs exactly ONE machine guard beyond the budget,
mirroring `_build_failure_retry_prompt` guard (a):

- **Identical run-smoke output two attempts in a row ⇒ stop early.** If the
  re-run-smoke `ToolResult.output` is bit-identical to the previous attempt's, the
  rebuild changed nothing observable — burning the rest of the budget is waste. This
  is the direct analogue of the `test_output == last_test_output` break at
  `agent.py` ~1986. A compact comparison (hash the output) is enough; no new
  abstraction.

Do NOT add a hypothesis-style guard at this layer — there is no debugger NarrowPass
in the outer loop; that guard lives correctly inside `code_with_retry`. The budget
(3) + the identical-output break are the minimal sufficient guards.

## Nesting / combined-bound note (flag for the plan)

The self-fix loop is an OUTER loop over the whole build→acceptance-verify cycle.
`code_with_retry` ALREADY runs its own inner retry loop (`max_debug_attempts`, +1
initial) for TEST failures, with `debug_pass` nested inside that. So:

```
total model build-calls ≈ (self-fix attempts) × (1 + max_debug_attempts)
                        = 3 × (1 + 2) = up to 9 full code_with_retry passes
```

per failing final task, each pass itself possibly running `debug_pass`. This is a
real combined bound the plan must acknowledge — on a slow local 14b model 9 build
passes on the last task is a long tail. **Flag for the plan:** the budget knobs are
*independent* (acceptance self-fix attempts vs. `max_debug_attempts`); the plan
should either (a) document the multiplicative worst case explicitly and accept it
(self-fix only fires on the LAST applicable task, so it is rare per plan), or (b)
consider a lower self-fix default if probe-time latency proves painful. Recommend
(a): accept the bound, document it, keep default 3 — self-fix is gated to a single
position (`should_run_now`) so the multiplier applies at most once per plan.

## Threat-model — FLAG only (orchestrator routes the edit post-coding)

This feature lands a NEW auto-resolution / autonomous-loop path, which the
threat-model Review note ("revisit when the trust model changes / a new
auto-resolution path lands") explicitly anticipates. Flag, do not edit:

- **T05 / T06 (autonomous loop):** the bounded self-fix loop is a new autonomous
  iteration surface. The budget (3) + the identical-output break + the trust gate are
  the bounding mitigations — these should be captured as / wired to a Security
  constraint `SCn` in `docs/architecture.md` §"Security constraints" post-coding.
- **T10 (wrong auto-resolution):** auto-fixing at `optimist`/`yolo` is a new place the
  model acts without per-step confirm; the skeptic-no-autofix gate is the mitigation.
- **Security-relevant surface touched:** yes — the loop runs shell (run-smoke) and
  applies patches autonomously under trust gating. Per `workflow/security-surfaces.md`
  this earns a Threat-row update + `Last reviewed` bump on the post-coding handoff.

## What the plan / coder must honor

1. Wire the loop in `plan_runner.py` `_run_task` (Q1-B), NOT in `plan_verify.py`.
   `verify_task` stays a pure reporter.
2. Carry the failing run-smoke `ToolResult.output` inline on the returned
   `TaskOutcome` (Q2-A) — new optional field, default `None`, preserved by `_demote`'s
   `dataclasses.replace`. Do NOT persist a new state field.
3. Trust gate = `policy.auto_confirm(trust)` (a machine check). At `skeptic`: record
   `failed`, stop — current behaviour unchanged.
4. Budget + on/off + any temperature in `config.py` `AgentConfig` (pydantic). Default
   ON, budget 3.
5. The retry prompt is assembled from the adapter-provided command + run-smoke output
   ONLY — zero language strings in `plan_runner` / the self-fix path.
6. One outer anti-loop guard: identical run-smoke output two attempts in a row ⇒ stop.
7. No new task-outcome status — reuse the deferred `done → failed` edge.
8. `_run_task` will grow; keep it under the 50-line function minimum by extracting the
   self-fix cycle into a private helper (`_self_fix_acceptance(...)` or similar) on
   `PlanRunner`.
9. Plan must document the multiplicative combined bound (~9 build passes worst case on
   the last task) and accept it (self-fix fires at one position only).
10. Post-coding: orchestrator routes the threat-model T05/T06/T10 row update + the
    `SCn` constraint for the bounded autonomous loop to `pm-architect` (this note only
    FLAGS them).
