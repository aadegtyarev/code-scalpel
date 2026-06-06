# Acceptance gate in run_plan — design notes

> Focused per-feature design note for `feat/acceptance-gate-run-plan` — step 2
> of the backend redesign (`.ai-pm/arch/backend-redesign_arch.md`). This is a
> **design note, not a doc rewrite**: `docs/architecture.md` stays AS-IS and is
> referenced. The post-coding "Docs to update" handoff (new Architectural
> decision + File-layout entries) is out of scope here, per the parent note
> (parent §"Plan notes for /pm-plan", last bullet).

## Context

The merged feature 1 (`feat/project-adapter-abstraction`) landed the adapter
contract but wired **nothing into the run loop** — the four ProjectAdapter
methods are non-abstract and "intentionally inert" (`code_scalpel/skills/base.py:149-191`).
This feature is the consumer: it adds **verification #4 (acceptance run-smoke)**
to `run_plan`'s per-task Definition-of-Done, and strangles `run_plan` out of the
3289-line `agent.py` monolith as it does so. It honors the parent note's
Fork 2 recommendation **"A as the floor"** for *this* feature (the python-cli
built-in default-floor; task-declared/narrow-pass specs are feature 4) and
Fork 3 recommendation **"B — strangle run_plan"**.

The structural choice is real on four axes (resolution below): (1) how the loop
resolves a root-bound acceptance adapter *generically* (no hardcoded
python-cli); (2) where verification #4 lives and its mandatory-vs-noop
semantics; (3) the strangle boundary; (4) state/TUI/trust surfacing.

The acceptance criterion **of the feature itself** is the v0.14 outcome gate:
**`notes_cli` 3/3 consistent `task_solved`** (parent note §Goal + migration
step 2; `docs/architecture.md` "outcome-driven release gate" decision). Confirmed
as this feature's own acceptance criterion.

## Adjacent implementations (verified this turn)

1. **The verification block** — `run_plan` in `code_scalpel/agent.py:1219`,
   verification block `agent.py:1458-1527`. Three machine checks run only when
   `outcome.status == "done"` (`_classify_outcome` at `agent.py:694` per the
   spawn brief; statuses `done|failed|skipped`, `TaskOutcome` at `agent.py:261`):
   (1) `_verify_task_files` (declared `Files:` exist), (2)
   `_verify_task_test_command` (`agent.py:1738`, `Test command:` exit-0 via
   `execute(..., trust="yolo")`), (3) git HEAD advanced. Demotion is **done→failed
   only** (each check rebuilds `TaskOutcome(..., status="failed")`). Verification #4
   slots **after** check 3, same `if outcome.status == "done"` scope.
2. **`_verify_task_test_command`** (`agent.py:1738-1770`) — the closest existing
   shape to run-smoke: builds a `shell_exec` `ToolCall`, runs `execute(..., trust="yolo",
   sandbox=..., shell_exec_timeout=...)`, maps `result.ok` → bool. **Critical
   divergence to honor:** it deliberately treats pytest exit 4/5 as *pass*
   (`agent.py:1758-1770`) because the plan inverts test-write ordering. The
   acceptance gate must **NOT** inherit that leniency — a run-smoke of the
   *finished* deliverable has no ordering excuse; non-zero exit (or timeout, or
   unresolvable pkg) is an unconditional fail.
3. **The skill-annotation pass** (`agent.py:1300-1308`) — the existing
   "surface an extra step via `on_tool_executed` synthetic card" pattern, the
   template for surfacing the acceptance step (resolution 4).
4. **Registry selection methods** (`code_scalpel/skills/registry.py`) —
   `get()`/`default()`/`default_runnable()` keep an **unfiltered** scan over
   `_skills` (lines 62-79), `all()`/`active()` filter `hidden` (lines 42-60).
   The new `acceptance_adapter(root)` is a **selection** method → unfiltered
   scan, so the `hidden=True` `PythonCliAdapter` (`python_cli_adapter.py:59`) is
   eligible. This is the established pattern.

## Behavioral risks in this area

- **No feedback loop introduced.** Run-smoke is a read-only-of-product shell
  invocation inside the verification block; it subscribes to nothing and
  mutates nothing that a subscription re-triggers. (Self-fix route-back —
  feeding run-smoke output *back* into `code_with_retry` — is feature 3 and is
  explicitly **out of scope**; that is where a loop *would* appear and must be
  bounded there.)
- **Trust path already precedented.** Run-smoke at `trust="yolo"` mirrors
  `_verify_task_test_command` exactly (`agent.py:1748-1757`) — same primitive,
  same trust, same sandbox/timeout config. No new trust axis (parent note,
  `policy.py` row: "Acceptance run-smoke is a shell/test action → already
  governed by trust. No new axis.").
- **Determinism of the check.** The floor command comes from
  `PythonCliAdapter.acceptance_spec` → `resolve_pkg` (`python_pkg.py:23`),
  fully deterministic; it raises (never guesses) on ambiguous/absent pkg. No
  model-derived input enters the gate at the floor (that is feature 4's risk).

---

## Question 1 — generic resolution of a root-bound acceptance adapter

**Proposed:** `provides_acceptance: bool` flag on `Skill`; `Skill.bind(root) -> Skill`
polymorphic method; `SkillRegistry.acceptance_adapter(root) -> Skill | None`
(unfiltered scan, first `provides_acceptance`, root-bound via `.bind(root)`).

### Variant A — flag + polymorphic `bind` + registry selector (the proposal)
- **Flag on `Skill`** (`provides_acceptance: bool = False`, override `True` in
  `PythonCliAdapter`): symmetric with the existing `provides_test_runner`
  (`base.py:69`) and `hidden` (`base.py:79`) class-attribute traits. Same
  mental model, smallest conceptual addition.
- **`bind(root)` as a polymorphic method** (default `return self`;
  `PythonCliAdapter` returns `PythonCliAdapter(root=root)`): the adapter *itself*
  owns how it root-binds — `PythonCliAdapter.__init__` already takes
  `root=...` (`python_cli_adapter.py:61`) and `run_smoke`/`acceptance_spec`
  already require it (`python_cli_adapter.py:92,109`). The knowledge of "what a
  bound instance is" lives with the adapter, not the registry.
- **`acceptance_adapter(root)` as a registry selection method**: unfiltered
  scan (matches `get`/`default`/`default_runnable`, `registry.py:62-79`), so
  `hidden` adapters are eligible; returns the first detecting `provides_acceptance`
  one, root-bound. One call site in the loop.

### Variant B — registry constructs the bound instance (no `bind`)
Registry's `acceptance_adapter` does `type(skill)(root=root)` itself instead of
calling `skill.bind(root)`.
- **Con:** the registry must know every adapter's constructor signature takes
  `root=`. PythonCliAdapter happens to (`root: Path | None = None`), but a future
  Node adapter (feature 5) or a component-skill might bind differently (e.g. a
  Node adapter binds to a `package.json` "bin" name, not just a root). `bind`
  keeps that polymorphic; `type(...)(root=...)` hardcodes one constructor shape
  into the registry — exactly the "registry re-litigates per-adapter knowledge"
  smell the parent note warns against (Fork 1 rationale).

### Recommendation: A (the proposal stands), with two refinements

1. **`bind` default should be `return self`** as proposed — but document it as
   the *identity bind* for adapters that need no root context, so component
   skills and the rootless discovery singletons are unaffected.
2. **Refine the flag's relationship to `bind`/discovery, not its name.** A
   subtle trap: the registry holds a **rootless** `PythonCliAdapter()` singleton
   (`python_cli_adapter.py:64-65` documents this as the detection/discovery
   instance). `acceptance_adapter` must **detect on the rootless singleton, then
   return the bound one** — never call `acceptance_spec`/`run_smoke` on the
   rootless instance (they raise, `python_cli_adapter.py:92,109`). The proposed
   ordering (scan → pick → `.bind(root)` → return) does exactly this; make it
   explicit in the plan so the coder does not accidentally probe a rootless
   instance.

**Forward-fit check (features 3/4/5):** the shape is right.
- *Feature 3 (self-fix):* needs the bound adapter's `run_smoke` argv + the
  failure output — `acceptance_adapter(root)` already hands back the bound
  instance, so feature 3 reuses it with no registry change.
- *Feature 4 (task-declared spec):* `acceptance_spec(task)` already takes the
  task (`base.py:185`); feature 4 enriches the *return value* (real round-trip
  vs floor), not the resolution path. No churn to question-1 surfaces.
- *Feature 5 (node adapter):* subclass + `provides_acceptance=True` + its own
  `bind`; `acceptance_adapter` picks it by priority/detect with **zero run-loop
  edit** — which is the whole point of the abstraction (parent note: "Adding a
  new language = subclass + register; no run-loop edit").

**Not overruled** — the proposed homes (flag on `Skill`, `bind` polymorphic on
the adapter, construction in a registry selector) are each the correct owner.

---

## Question 2 — where verification #4 lives + mandatory-vs-noop semantics

**Proposed:** 4th check after the existing three; mandatory when
`acceptance_adapter(root)` resolves (fail/timeout/unresolvable-pkg demotes
done→failed); logged no-op when no adapter detects.

### Placement
Insert **after** check 3 (git HEAD), inside the same `if outcome.status == "done"`
block (`agent.py:1470-1527`), as a final `if outcome.status == "done":` sub-gate
(the running outcome may already have been demoted by checks 1/2; only run-smoke
a still-`done` task). Demotion uses the **same** `TaskOutcome(..., status="failed")`
rebuild the three existing checks use (`agent.py:1473-1489`) — no new status
value, no new demotion direction (done→failed only, preserving the parent note's
"Preserve: existing three checks, `_classify_outcome`").

### Semantics — recommendation: **mandatory-when-resolves, noop-otherwise (confirmed)**
This is exactly the parent note's "A never lets the gate be skipped — it is the
minimum" applied at the floor:
- **`acceptance_adapter(root)` resolves** (python-cli / notes_cli) → run-smoke
  is **mandatory**. A failing exit, a timeout, OR an unresolvable pkg demotes
  done→failed. The gate **cannot** be silently skipped for a type the floor
  covers.
- **No adapter detects** (unsupported project type) → **logged no-op**, status
  unchanged. This preserves existing behavior for types the floor does not yet
  cover, rather than failing every non-python project — correct for a *floor*
  (the floor is a minimum, not a universal wall). Surface the no-op via the
  `on_tool_executed` card so "we did not run-smoke this type" is visible, not
  silent.

**Do NOT inherit `_verify_task_test_command`'s exit-4/5 leniency**
(`agent.py:1758-1770`). That leniency exists only because the plan inverts
test-write ordering; a run-smoke of the finished deliverable has no such excuse.
Run-smoke: `result.ok` (exit 0) → pass; anything else → fail. State this
explicitly in the plan so the coder does not copy the lenient mapping wholesale.

### Unresolvable `<pkg>` (resolve_pkg raises) — recommendation: **failed, not a new indeterminate status**
The proposal (classify as `failed`) is correct, and I **decline** to add a
distinct indeterminate status — with rationale:
- The product premise (parent note §"New goals": "Determinism is the product";
  diagnosis: the `__main__.py` coin-flip is *exactly* a not-`-m`-runnable
  deliverable) means **"cannot resolve a runnable package" IS the failure the
  gate exists to catch.** A deliverable whose package can't be resolved is, from
  the user's standpoint, not runnable — that is a failed task, not an "unknown".
- Adding a third status would force `_classify_outcome`, `TaskOutcome`, the TUI
  outcome rendering, and STATE persistence to all learn a new value — a large
  blast radius for a distinction that maps onto "failed" anyway at the floor.
- **Refinement (not an overrule):** distinguish the *reasons* in the **logged /
  persisted message + the synthetic card**, not in the status enum:
  `acceptance: pkg-unresolvable` vs `acceptance: run-smoke exit N` vs
  `acceptance: timeout`. Feature 3 (self-fix) will want that reason text as its
  failure signal anyway — capture it now as a string, demote to `failed` now.
  This gives the diagnostic value of an indeterminate state without a schema
  change.

**Refined, not overruled** — placement and mandatory-vs-noop confirmed; the
exit-4/5 leniency exclusion and the reason-in-message (not in enum) treatment
are sharpening, not reversal.

---

## Question 3 — the strangle: extracting `run_plan` into its own module

**Proposed:** commit 1 = behavior-preserving extraction of `run_plan` (+ private
helpers) into a `PlanRunner` collaborator the StepAgent delegates to (existing
tests unchanged/green); commit 2 = add the gate.

### Variant A — delegating `PlanRunner(agent)` collaborator (the proposal)
`StepAgent.run_plan(...)` becomes a thin delegator:
`return await PlanRunner(self).run(...)`. The runner reaches back through the
held `StepAgent` for the `self.*` it needs.
- **Pro:** smallest, safest behavior-preserving move — the body relocates almost
  verbatim, `self.` → `self._agent.`. Existing `run_plan` tests stay green
  because the public method signature on `StepAgent` is unchanged (the parent
  note's hard requirement: "existing run_plan tests unchanged and green").
- **Con:** `PlanRunner(self)` holding the whole `StepAgent` keeps the coupling
  wide (it can touch *anything* on the agent) — it shrinks `agent.py`'s line
  count without yet narrowing the dependency surface.

### Variant B — explicit-dependency `PlanRunner(deps...)` (constructor-injected seam)
Pass only the needed collaborators explicitly (config, cwd, state, upstream
queue, `code_with_retry` callable, git/test helpers).
- **Pro:** the seam is documented as a real interface; aligns with the project's
  "DI through the constructor / composition root" constraint (`CLAUDE.md`).
- **Con:** the dependency surface is **large** (enumerated below) and several
  are *private methods* of `StepAgent` (`_verify_task_files`,
  `_verify_task_test_command`, `_git_head_sha`, `_auto_commit_task`,
  `_ensure_git_repo`, `_run_plan_shell`) — injecting bound methods is awkward and
  risks *behavior change* (the exact failure mode the strangle commit forbids).

### Recommendation: **A for commit 1, with B as the explicitly-documented next step**

Take **Variant A** to satisfy the behavior-preservation requirement cheaply and
keep commit 1 a pure move (`PlanRunner(self)` / `self._agent.*`). **But document
the seam** (the `self.*` the runner needs) so the wide coupling is a *known,
listed* surface, not accidental — and so a later opportunistic step (parent note
migration item 6) can narrow `PlanRunner(self)` → `PlanRunner(explicit deps)`
without re-discovering the boundary.

**Module name:** `code_scalpel/plan_runner.py`, class `PlanRunner`. (Mirrors the
existing `code_scalpel/plan.py` which owns `Task`/parse/render; `plan_runner.py`
owns *execution* of that plan. Reads naturally beside it.)

**The seam — `self.*` the extracted runner needs** (verified against
`agent.py:1219-1695` + the helpers):
- *Config:* `self._config` (agent.auto_git, auto_commit_on_done,
  auto_annotate_plan, shell_exec_timeout, sandbox, max_file_lines).
- *Context:* `self._cwd` (root for TASKS paths, execute cwd, `acceptance_adapter(root)`).
- *State:* `self._state` (completed_tasks, current_task — and the **new**
  acceptance field, resolution 4).
- *Upstream:* `self._upstream_queue` (`record_commit`).
- *Engine:* `code_with_retry` (the per-task dispatch) and `self._shell_runner`
  (passed to `execute`).
- *Helpers (private):* `_classify_outcome` (module fn, not a method — already
  free), `_verify_task_files`, `_verify_task_test_command`, `_git_head_sha`,
  `_auto_commit_task`, `_ensure_git_repo`, `_run_plan_shell`.
- *Seam hooks:* the `on_task_start`/`on_task_end`/`on_tool_executed` callables
  (passed *through* `run`, already parameters — no new coupling).

**Plan should be updated to:** make commit 1's "tests unchanged & green" an
explicit gate before commit 2 starts — i.e. the strangle lands and is verified
green *before* the gate is added, so a `notes_cli` regression after commit 2 is
unambiguously the gate, not the move.

**Refined, not overruled** — `PlanRunner` collaborator confirmed; `PlanRunner(self)`
for commit-1 safety (not constructor-injected yet) and the named module are the
sharpening.

---

## Question 4 — state + TUI + trust

**Proposed:** persist last run-smoke command+verdict in `AgentState` (new
field); ride existing `on_task_end` (`done` now means "ran") + surface the
acceptance step via the `on_tool_executed` synthetic-card pattern; execute at
`trust="yolo"` even on a skeptic project.

### State — confirmed, with field shape
Add to `AgentState` (`code_scalpel/state.py:34`), default-valued so existing
STATE.json loads forward-compatibly (pydantic v2, like the v0.12.5 additions at
`state.py:47-58`):
- `last_acceptance_command: str | None = None`
- `last_acceptance_verdict: Literal["passed", "failed", "noop", "unknown"] = "unknown"`

Persisted in the existing task-end `self._state` block (`agent.py:1537+`), inside
the same `with suppress(Exception)` defensive guard, via the existing atomic
`save()` (`state.py:60`). The `failed` verdict should carry the **reason string**
from question 2 — store it too (`last_acceptance_reason: str | None = None`) so
resume/metrics and feature-3 self-fix have the signal. (`noop` = no adapter
detected; preserves the question-2 distinction in persistence without an outcome
status.)

### TUI — confirmed (no structural change)
- Ride `on_task_end` — a `done` outcome now genuinely means run-smoke passed
  (parent note: "a `done` now genuinely means 'ran'"). No new outcome field.
- Surface the acceptance *step* via the existing `on_tool_executed` synthetic
  card (the same pattern the annotation pass uses, `agent.py:1300-1308`): emit a
  synthetic `ToolCall(name="acceptance", ...)` + its result so the user **sees**
  run-smoke executed (and sees the `noop` case for unsupported types). This is
  the parent note's "safe default, not a freeze" — no seam change needed for the
  floor; a distinct "acceptance failed → self-fixing" hook is **feature 3's**
  call, deliberately out of scope here.

### Trust — confirmed, with the security/UX note the spawn asked for
Run-smoke at `trust="yolo"` is correct and **already precedented**:
`_verify_task_test_command` runs the user's plan-declared command at
`trust="yolo"` today (`agent.py:1748-1757`), with the documented rationale "the
user explicitly authored the command in TASKS.md and accepted the plan, so it's
not a model-injected command that needs the skeptic confirmation gate"
(`agent.py:1739-1747`).

**Security/UX concern, surfaced as requested:** there *is* a real difference in
**provenance** between the two at the floor. `_verify_task_test_command` runs a
command the user **authored** (`Test command:` in TASKS.md). The floor
acceptance command is **adapter-derived** (`PythonCliAdapter.acceptance_spec`
→ `python -m <pkg> --help`), not user-authored — so the "user accepted this exact
command" justification is **weaker** at the floor than for the test command.

- **Why it is nonetheless acceptable at yolo for THIS feature:** the floor
  command is **fully deterministic and adapter-code-owned** (`python -m <pkg>
  --help`, pkg resolved by `resolve_pkg`, never model-emitted) — it is *more*
  trustworthy than a model-injected command, and arguably more than a
  free-text user-authored one, because no untrusted text reaches the shell. It
  runs the *deliverable the user already approved by hitting /go*, with a
  fixed, inspectable verb (`--help`). The blast radius is "run the thing the run
  was about to produce anyway."
- **The flag for the plan / future features:** when **feature 4** lets a
  **task-declared or narrow-pass-derived** acceptance command in, the
  narrow-pass-derived variant is **model-derived text executed at yolo** — that
  *does* re-introduce a model-controlled string into a yolo shell on a skeptic
  run. That is a security decision feature 4 must make explicitly (confirm gate
  for narrow-pass-derived commands? restrict to a safe verb set? require
  write-back + user inspection before first run?). **This feature's floor is
  safe; feature 4 must not blindly extend yolo to model-derived commands** — note
  it in feature 4's plan, do not solve it here.

**Confirmed, with one surfaced flag** (the floor is safe at yolo; the
provenance argument weakens for feature 4's model-derived specs — flagged
forward, not changed here).

---

## What this note does NOT cover (deferred)

- **Self-fix route-back** (feature 3, `feat/acceptance-self-fix-loop`): feeding
  run-smoke failure output back into `code_with_retry`. This note captures the
  *failure reason string* so feature 3 has its signal, but adds **no** retry
  loop. The acceptance gate here only **demotes done→failed**; it does not
  attempt repair.
- **Task-declared / narrow-pass acceptance specs** (feature 4,
  `feat/acceptance-spec-in-tasks`): `Task.acceptance` (`code_scalpel/plan.py`,
  exists but UNUSED) and the narrow-pass fallback + write-back. This feature
  uses **only** the python-cli built-in default-floor (`acceptance_spec`'s
  current return, `python_cli_adapter.py:99-114`). Parent Fork 2 "A as the
  floor" for this feature.
- **Node / second-language adapter** (feature 5, `feat/node-cli-adapter`). This
  feature's `acceptance_adapter` resolution is *designed* to pick it up with no
  run-loop edit, but feature 5 ships the subclass.
- **Further `agent.py` decomposition** beyond `run_plan` (parent migration item
  6, opportunistic).
- **`docs/architecture.md` update** (new Architectural decision + File-layout
  entries) — the normal post-coding "Docs to update" handoff, explicitly **not**
  part of this design note (parent note, last bullet).

## Acceptance criterion of the feature itself

Confirmed: **the v0.14 outcome gate — `notes_cli` 3/3 consistent `task_solved`**
— is this feature's own acceptance criterion (parent note §Goal + migration step
2; `docs/architecture.md` "outcome-driven release gate"). The feature's plan
should also carry the Product Contract `## Must not break`: *a `done` task means
run-smoke passed — no regression to proxy-only "done"* (parent note §Plan notes,
bullet 1).
