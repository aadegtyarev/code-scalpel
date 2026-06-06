# Architecture

> Canonical architecture for code-scalpel. Owned by `pm-architect`.
> Finalized at legacy adoption from the `pm-codebase-reader` draft (facts
> extracted from `code_scalpel/` source + `docs/plan.md`, the project's
> pre-existing ~3910-line living design doc) and `docs/stack-notes.md`.
> Where code and `plan.md` disagree, code is ground truth; residual
> uncertainties carry `(inferred)` or `[?]`.

---

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.11+ | `StrEnum`, `X \| None` syntax, `asyncio.TaskGroup`; weak-model agent is I/O-bound, not CPU-bound |
| Runtime model | `asyncio` (async everywhere there is I/O) | LLM calls, shell, HTTP all overlap; ESC-cancellable streaming |
| TUI framework | `textual` (+ `textual-autocomplete`) | modern, async-native terminal UI; cards stream tokens into widgets; slash-command completion |
| CLI | `typer` (on `click`) | bare `code-scalpel` launches TUI; `code-scalpel init` onboarding subcommand |
| Config | `pyyaml` + `pydantic` v2 (`BaseModel`) | YAML config files, schema-validated; layered system → project → env |
| Secrets | `python-dotenv` / env vars | API keys never in YAML — `*_API_KEY` env only |
| LLM transport | `openai` SDK (`AsyncOpenAI`) | one OpenAI-compatible adapter covers LM Studio, llama.cpp, OpenRouter, vLLM, Ollama |
| LLM native surface | `lmstudio` SDK (`>=1.5`) | LM Studio model load/unload/swap + native streaming events; used for the upstream model-swap on single-GPU hosts |
| Code symbols / index | `tree-sitter` + `tree-sitter-python` + `ast` fallback | granular symbol index; **only the Python grammar pack is a declared dep** — other languages degrade to `ast` |
| Diff / patch | own `patch/edit_block.py` (SEARCH/REPLACE) + `unidiff` (parse only) | weak models can't emit valid unified-diff line counters; SEARCH/REPLACE applies, `unidiff` only parses for display |
| URL → markdown | `html2text` | render fetched pages for `/learn --url` |
| `.gitignore`-aware listing | `pathspec` | file walking honours `.gitignore` |
| Git / ripgrep | `subprocess` via async ShellRunner | direct `git` and `rg` calls; pure-Python grep fallback when `rg` absent |
| HTTP fetch | `httpx` | `/learn --url`, web search |
| Persistent memory | `sqlite3` + FTS5 (stdlib) | project notes with BM25 search, zero new deps (mem0ai spike rejected) |
| Shell sandbox | `bubblewrap` (`bwrap`) wrapper | optional kernel-level isolation for model-issued shell commands (Linux only) |
| Diagram render | `@mermaid-js/mermaid-cli` (`mmdc`, npm) + `rich-pixels` (optional `[diagrams]`) | render mermaid blocks from model replies inside the TUI |
| Token estimate | `len(text) / 4` heuristic | good-enough budget accounting for local models |
| Build | `hatchling` + `pyinstaller` (`[build]`) + `nfpm` | `pyproject.toml` is the single config home; standalone binary + `.deb` |
| Lint / format / types / test | `ruff`, `mypy --strict`, `pytest` + `pytest-asyncio`, `pytest-cov` | enforced in CI + pre-commit; `@pytest.mark.llm` tests hit live LM Studio under `--run-llm` |

**LLM backend.** Default profile is `qwen2.5-coder-14b-instruct` in **LM
Studio** at `http://localhost:1234/v1`. Any OpenAI-compatible endpoint
works through the same adapter. Cross-model bench (`docs/bench-models.md`)
keeps `coder-14b` as the Pareto-optimal default; `gemma-4-26b-a4b` is the
max-quality alternative.

**Target platform.** Linux primary (`bwrap` sandbox, standalone binary +
`.deb` release artifacts are Linux-only). Terminal/TUI; no web or GUI.

## Architectural decisions

### Weak-model-first design — small everything

**Chosen:** small task / small context / small patch / fast test /
controlled autonomy.
**Why:** the product exists to make a 7B–14B local model do reliable code
work. Every design choice optimises for what a weak model can actually do.
**Rejected:** "autonomous programmer" / large-context approaches — a weak
model loses coherence; this is explicitly *not* a Claude-Code replacement
(`plan.md` §1).

### SEARCH/REPLACE then tool-call `write_file` over unified diff

**Chosen:** v0.1 moved from unified diff to aider-style SEARCH/REPLACE
blocks (15/15 vs 13/15 apply success). v0.7 moved again to a tool-call
`write_file` with explicit `overwrite / replace_lines / insert_after_line`
modes.
**Why:** qwen-14b mis-counts `@@` hunk headers and trips on
whitespace/tabs in SEARCH blocks; explicit tool-call parameters are far
more stable.
**Rejected:** unified diff (counter errors), raw SEARCH/REPLACE as the
primary path (whitespace drift) — both kept only as compatible fallbacks.
`unidiff` is retained for diff *parsing/display* only, never application
(`docs/stack-notes.md` patch-engine entry).

### Narrow passes — many small role-specialised turns beat one fat turn

**Chosen (v0.8):** instead of one big prompt, run several one-shot
`NarrowPass` LLM calls each with a single role (skill annotator, per-step
reviewer, test-sanity judge, commit-message writer, fork picker/reviewer,
debug hypothesiser).
**Why:** a local model is nearly free, so 2–3 extra single-purpose calls
buy quality. Each pass has its own temperature and no tool/history thread.
**Rejected:** one monolithic prompt that asks the model to wear all hats.

### Machine checks over prompt instructions

**Chosen (v0.9):** if a thing can be verified by a machine, verify it
(lint pass, import-graph check, empty-test detector, mkdir guard,
`content=""` reject, per-task git-HEAD validation) rather than asking the
prompt to behave.
**Why:** a machine check is temperature-independent and can't be talked
out of by the model.

### Fork delegation by trust level

**Chosen (v0.10/0.11):** architectural choices ("which stack?", "which
library?") are delegated through a single `fork()` API; *who answers* is
derived from the same `trust` knob that gates shell/patch
(skeptic→human, optimist→timed-human-then-auto, yolo→auto). A separate
stronger "upstream" model resolves forks in **batches**, not per-fork
(v0.12).
**Why:** the 14b builder is a poor judge of architecture; one trust axis
means fewer mental models and fewer bugs. Batching amortises the cost of a
paid API / GPU model-swap.
**Rejected:** a dedicated `fork_resolver` config + `/fork` command (built
then removed in v0.10a — collapsed into `trust`).

### One headless Runtime channel for every entry point

**Chosen:** `Runtime` owns the (session, llm, memory, agent) quartet; TUI,
probe, bench, spy all build it the same way and run turns through
`Runtime.stream()` / `.ask()`.
**Why:** a prior bug — the TUI appended a "(Reply in X.)" suffix via
`Session.prepare_turn` that the probe didn't — made the same model behave
differently in TUI vs probe. Collapsing channels into one class makes TUI
behaviour reproducible from a probe.

### Outcome-driven release gate (v0.13+)

**Chosen:** the real release *signal* is an end-to-end probe scenario
(`notes_cli`) run N≥3 times to a "task_solved" verdict, not capability
micro-probes. Single runs are sampler noise, not signal.
**Why:** integration catches what layer-level probes miss; single-run
narratives about "watershed" versions were repeatedly disproven.
**Status:** the N≥3 outcome probe is run **manually** today; it is **not**
wired as an automated CI gate (the lint/type/test CI is — see Release
flow). The automated outcome gate is v0.13 backlog `(inferred)`.
**The `notes_cli` 3/3 `task_solved` signal now has teeth (v0.14,
`feat/acceptance-spec-in-tasks`):** the acceptance run-smoke that gives
`done` real meaning is now **enforcing** where an applicable spec exists
(see *Acceptance gate enforcement (verification #4)* below), so the 3/3
gate is the live, enforced release signal — a task that doesn't actually
run its derived CLI deliverable is demoted, no longer just recorded. The
3/3 probe is still run manually before ship. **Honest current bound:** the
gate enforces only at the plan's final step (see the limitation in the
*Acceptance gate enforcement* decision), so a plan whose runnable CLI is
built by an earlier task and whose final task is non-CLI (tests/docs) is
*observed*, not enforced — full consistent `notes_cli` 3/3 also depends on
later work (feature 3, self-fixing mid-plan failures). The gate's current
guarantee is "never false-fail; enforce at the final step where applicable".

### ProjectAdapter — `Skill` as a superset run/scaffold/acceptance contract (v0.14)

**Chosen:** the existing per-stack `Skill` ABC (test/lint/format) gains
four **non-abstract** capability methods — `build_install()`,
`run_smoke(args)`, `scaffold(spec)`, `acceptance_spec(task)` — that turn a
skill into a full *project adapter*: not just how to test, but how to
build/run/scaffold the actual deliverable. A `ScaffoldSpec` dataclass
(`root`, `pkg`) carries the scaffold inputs. The first concrete adapter is
`PythonCliAdapter`, which delegates `detect`/`test_cmd`/`lint_cmd` to
`PythonSkill` (the test path never drifts), adds `pip install -e .`,
`python -m <pkg> <args>` run-smoke, a code-owned src-layout scaffold, and a
built-in default-floor acceptance spec.
**Why:** the proven `notes_cli` failure is that the agent never runs the
deliverable as a user would and the `__main__.py` entrypoint was a
model-emitted coin-flip (`.ai-pm/arch/backend-redesign_arch.md`, step 1 of
the backend redesign). Moving run/scaffold/acceptance into a deterministic,
code-owned adapter is what removes that whim; extending `Skill` (rather than
a parallel hierarchy) reuses detect + registry + priority and keeps one
mental model (Fork 1-A in the design note).
**Non-abstract invariant:** all four ship with safe defaults
(`build_install`/`run_smoke`/`scaffold` → `[]`, `acceptance_spec` → `None`),
so **no existing skill becomes abstract** — Go/JS/Docker/Postgres/SQLite/
Markdown all still instantiate unchanged.
**`<pkg>` deterministic resolution (`python_pkg.resolve_pkg`):** the
package run as `python -m <pkg>` is resolved from the project, never
guessed, in fixed precedence — (1) the hatchling wheel target declared in
`pyproject.toml`, (2) a single `-m`-runnable package under `src/` (has
`__main__.py`), (3) a single package dir under `src/`; ambiguity or absence
raises rather than guess. **Reach gap (documented):** resolution is
**src-layout/hatchling only** today — a setuptools flat-layout project does
not resolve and its acceptance run-smoke is **skipped** (recorded
`pkg-unresolvable`, never demoted); flat-layout reach is a follow-up.
**Scaffold honors the stack invariants (`docs/stack-notes.md`):** the
emitted `pyproject.toml` declares
`[tool.hatch.build.targets.wheel] packages = ["src/<pkg>"]` (hatchling
src-layout), and the package gets a real `__main__.py` (a
`[project.scripts]` console entry alone does **not** make `python -m <pkg>`
work). The scaffold never clobbers existing files (fails loud) and rejects
invalid package names before writing anything.
**Status — contract landed; first run-loop consumer is the observational
acceptance run-smoke (v0.14, see below); now enforcing (v0.14, feature 4).**
This feature only made the contract *exist*; the run-loop consumer arrived
with `feat/acceptance-gate-run-plan` (observational), and
`feat/acceptance-spec-in-tasks` gave it teeth (see *Acceptance gate
enforcement* below). `build_install`/`scaffold` remain unconsumed by the
run loop.
Source: `.ai-pm/arch/backend-redesign_arch.md` (Fork 1-A, migration step 1);
`docs/features/project-adapter-abstraction_plan.md`; shipped in
`code_scalpel/skills/base.py` + `python_cli_adapter.py` + `python_pkg.py`.

### Registry `hidden` trait — discoverable without advertising (v0.14)

**Chosen:** a `Skill` gains a `hidden: bool = False` class trait. A hidden
skill stays **registry-discoverable** (`get_skill(name)`, `default`,
`default_runnable` still see it) yet is **excluded from every model-facing
listing** — the catalog `all()`, the active-skills listing `active()`, the
detected-stack hint, and the `/skills` panel that build on them.
`PythonCliAdapter` sets `hidden = True`: it shares `PythonSkill`'s
`detect()`, so on a Python project it would otherwise show a duplicate
catalog row backed by no `prompts/skills/python-cli.md` guidance.
**Why:** the adapter must be reachable for the future run-loop that
constructs it deliberately, without polluting the model's skill catalog or
hijacking the test path (it is also registered with
`provides_test_runner = False`, so `default_runnable` keeps selecting
`PythonSkill`). This is the **listing-vs-selection split** in the registry:
`all()`/`active()` (listing) filter on `hidden`; `default`/`default_runnable`/
`get` (selection/detection) keep their own unfiltered scan, so detection
behavior is unaffected. Registration is explicit in `skills/__init__.py`
(the module is `python_cli_adapter.py`, not `*_skill.py`, so the
auto-scanner skips it).
Source: `docs/features/project-adapter-abstraction_plan.md` (scenario 7 +
interaction scenarios); shipped in `code_scalpel/skills/base.py`,
`registry.py`, `__init__.py`.

### Acceptance run-smoke (verification #4) in `run_plan` — observational (v0.14)

**Chosen:** `run_plan` runs a 4th machine check after the existing three
(declared `Files:` exist, `Test command:` exits 0, per-task git HEAD
advanced). When a registry-resolved acceptance adapter detects the project
root, the runner **runs the deliverable the way a user would** — the
adapter's `acceptance_spec(task)` command (`python -m <pkg> --help` at the
floor) through the existing gated `execute(...)` shell path — and
**records + surfaces** the verdict (`passed` / `failed` / `noop`). The
resolution is generic: `provides_acceptance: bool` flag on `Skill`, a
polymorphic `Skill.bind(root)` (default `return self`; the adapter owns
how it root-binds), and `SkillRegistry.acceptance_adapter(root)` (an
unfiltered scan returning the first detecting `provides_acceptance` skill,
root-bound) — so a future language adapter (feature 5) needs no run-loop
edit.
**Observational, not enforcing — never demotes (PM "plumbing only"
decision).** This iteration ships the run-smoke **plumbing + observability
only**: it records and surfaces the verdict but **never demotes a task to
`failed`**. The `done | failed | skipped` taxonomy is **unchanged** and a
`done` task does **not** require run-smoke to pass — checks 1–3 alone still
decide the verdict. **Superseded (v0.14):** verification #4 now **enforces**
where an *applicable* spec exists — see *Acceptance gate enforcement
(verification #4)* below; this entry documents the observational phase the
enforcing gate grew out of. **Why deferral (then):** the floor adapter (`PythonCliAdapter`)
detects *any* Python project and cannot tell a CLI deliverable from a plain
library without a CLI-intent signal; demoting now would wrongly fail `/go`
runs over Python **libraries** (a net-new regression). Hard enforcement
(demote-on-failure behind the CLI-intent signal) is deferred to feature 4
(`feat/acceptance-spec-in-tasks`).
**Floor only.** The recorded `passed` is exit-0 at the floor
(`expected == ""`); when an adapter returns a non-empty `expected`
observable the run-smoke output must additionally contain it. A failing
exit, a timeout, or an unresolvable package records `failed` with a reason
string (`run-smoke exit N` / `timeout` / `pkg-unresolvable`); no adapter
detecting the type records a logged `noop`. Richer round-trip specs
(`add 'x' → list shows it`) and task-declared `Acceptance:` consumption are
feature 4; the floor catches only the diagnosed "does not run at all"
failure. The run-smoke command is **code-owned and deterministic** (resolved
by `resolve_pkg`, never model-emitted) and executes at `trust="yolo"` as a
plan-owned machine check, mirroring `_verify_task_test_command` (see
`docs/threat-model.md` and `SC2`/`SC3`). Unlike the test-command check it
does **not** inherit the pytest exit-4/5 leniency — a finished deliverable
has no test-ordering excuse.
Source: `.ai-pm/arch/backend-redesign_arch.md` (migration step 2);
`.ai-pm/arch/acceptance-gate-run-plan_arch.md`;
`docs/features/acceptance-gate-run-plan_plan.md`; PM re-scope in
`.ai-pm/reviews/acceptance-gate-run-plan_review.md` `## Resolutions` #1;
shipped in `code_scalpel/plan_runner.py` + `plan_loading.py` +
`plan_post_checks.py` + `plan_verify.py` (`_verify_acceptance`),
`skills/base.py` + `python_cli_adapter.py` + `registry.py`, `state.py`.

### Acceptance gate enforcement + derived/declared acceptance specs (v0.14)

**Chosen:** verification #4 (the acceptance run-smoke) flips from
record-only to **enforcing** — it demotes `done → failed` — but **only when
three independent signals agree** (intent × position × state). This is the
post-probe timing model that replaced the original "applicable alone
enforces" rule, which a live greenfield probe showed never engaged (intent
was being judged against an empty filesystem, so everything came back
not-applicable). The whole shape:
- **`AcceptanceSpec(command, expected, applicable, source)`** (frozen
  dataclass) replaces the old `(command, expected)` tuple. `command` is the
  adapter-built argv-string; `expected` is the observable substring (`""` =
  exit-0-only); **`applicable` is the INTENT signal** (is this *meant* to be
  a runnable CLI deliverable?); `source ∈ {declared, derived, floor}`.
- **The three signals, demote IFF all three:**
  - **Intent** — `spec.applicable`: judged **pre-loop from the plan/task
    TEXT** ("is this deliverable *meant* to be a runnable CLI?"), **not**
    from the filesystem, so it is stable from task 0 and correct on a
    greenfield/empty repo. The default-floor never sets it, so libraries
    and no-spec projects are not applicable.
  - **Position** — `should_run_now`: computed in the run-loop as **pure
    plan structure** (the task is the structurally **last not-done task**).
    Pure structure, no LLM, no language string — answers "has the plan
    reached the point where the deliverable should be runnable end-to-end?"
  - **State** — `run_smoke_ok`: the **deterministic run-smoke at verify
    time** (run the deliverable as a user would; non-empty `expected` must
    appear). Needs files, so it is judged last.
  Demotion fires **iff `applicable AND should_run_now AND not run_smoke_ok`**
  — intent says CLI, position says it should run by now, state says it
  doesn't. Anything else is **observational** (record + surface, no demote).
- **Early-task observe guarantee (case c).** An **applicable but
  non-final** task — the CLI exists in intent but is not yet supposed to be
  runnable — is **observed, never demoted** (`should_run_now` is False).
  This is what fixed the greenfield false-demote: building the CLI across
  several tasks no longer fails the early skeleton task. Together with the
  two existing locks — not-applicable (library) → observed, and the
  default-floor → observed — only the *should-run-now-but-broken* case
  demotes (the narrowest possible demoting surface).
- **Spec precedence: derived (C) → floor (A).** A **narrow-pass-derived**
  spec (C) is **args-only**: the model returns `{applicable, args,
  expected}` and the **adapter** builds the run argv from `args` (no
  free-form shell — PM security decision; see `## Security constraints`
  `SC7` and `docs/threat-model.md` T12). The derived spec is **written back
  into the plan** so it is deterministic on every later run (no
  re-derivation). A **human-declared prose acceptance (B) is a HINT to the
  derivation, NOT executed as a command** — `Task.acceptance` is free prose
  with no runnable-args shape, so executing it as argv false-demoted tasks;
  direct enforcement of a *structured* declared spec is a follow-up.
- **The run-loop is language-agnostic.** It asks the `detect()`-selected
  adapter for an `AcceptanceSpec`, runs `spec.command`, and ANDs
  `spec.applicable` (from the adapter) with `should_run_now` (a structural
  bool it computes itself) — **zero language strings in the loop**. A future
  Node adapter (feature 5) plugs in with no run-loop edit. A single
  `acceptance_applicable(task)` adapter method is the one source of the
  intent decision (used by both the normal and the pkg-unresolvable paths,
  so applicability never diverges).
**Why:** feature 2 shipped the run-smoke as observational because a
demoting gate over *any* Python project wrongly fails libraries with no CLI
deliverable. The applicability discriminator gives the gate teeth without
re-creating that regression; the position signal then prevents the
*greenfield* false-demote a live probe exposed (an early not-built-yet task
must not be failed just because the CLI isn't wired yet). A `done` task that
is applicable, final, and ran means the deliverable actually worked.
**Known limitation (documented, honest under-enforcement).** Enforcement
fires only on the **last not-done task** (the position proxy). When the
runnable CLI is built by an **earlier** task and the **final** task is
non-CLI (tests/docs), the gate **observes rather than enforces** — safe
**under-enforcement** (it never produces a *false failure*, it just misses a
real one). A fuller "deliverable complete" signal, plus the model
self-fixing mid-plan failures (consistency), is later work (feature 3 /
follow-up). The `resolve_pkg` **flat-layout reach gap** (src-layout/hatchling
only — see the ProjectAdapter decision) compounds this: a setuptools
flat-layout project skips run-smoke entirely, also under-enforcing. The
current contract is therefore **"never false-fail; enforce at the final
step where applicable"** — not yet "every broken intermediate CLI fails".
**Taxonomy unchanged.** No new status — enforcement reuses the existing
`done → failed` demotion (the edge that was inert in feature 2 now fires
where all three signals agree). See `### Task outcome status` and
`## State model`.
**Config:** `auto_derive_acceptance` (default `True`) gates the pre-loop
derivation LLM pass (mirrors `auto_annotate_plan`); a headless/hermetic
caller can disable it.
Source: `.ai-pm/arch/acceptance-spec-in-tasks_arch.md` (resolutions 1–5
+ `## Timing fix (post-probe)`); `docs/features/acceptance-spec-in-tasks_plan.md`;
PM args-only security decision + the post-review B-is-a-hint resolution
(`.ai-pm/reviews/acceptance-spec-in-tasks_review.md`); the intent/position/
state timing fix shipped in `code_scalpel/plan_verify.py` (the three-signal
demotion gate), `plan_runner.py` (`should_run_now` position signal),
`plan_loading.py`, `prompts/derive_acceptance.md` (intent-not-state re-scope),
`skills/base.py` (`AcceptanceSpec` + `acceptance_applicable`),
`skills/python_cli_adapter.py`, `agent.py` (`derive_acceptance_args`),
`config.py` (`auto_derive_acceptance`), `state.py`.

## Architectural constraints

- **Stay inside the project root.** Subprocess cwd is pinned to the
  project root; `policy.py` hard-blocks `cd`/`pushd`/redirect/`cp`/`mv`
  that would write outside it, even without the sandbox.
- **DI through the constructor; `app.py` (TUI) / `Runtime` is the single
  composition root.** No global singletons for llm/session/memory/agent.
- **No model-run path may bypass `Runtime` + `Session.prepare_turn`.**
  Direct `StepAgent.stream_ask` calls diverge from what the user sees
  (`DEVELOPING.md` "Каналы прогона модели").
- **API keys never in YAML** — env / `.env` only.
- **All public functions/methods are type-annotated; `mypy --strict`
  clean is a merge blocker.**
- **Tests ship with code** — a new module without a test is not committed.
- **No magic numbers** — tunables live in `config.py` (pydantic).
- **AI-minimums (max ~300 lines/file, ~50/function, complexity ≤ 10) are
  convention, not linter-enforced today** — see `### AI-specific
  minimums`. Several core modules exceed the file ceiling (`agent.py`
  ~2840 lines, `tui/app.py` ~2129 lines).

## Operational limits & budgets

- Typical target project: **10–100 files, 100–500 lines/file**, model
  context window **16k–32k tokens**, local LLM **7B–14B** (`plan.md` §2).
- Context budget thresholds (config, fraction of window): warn `0.70`,
  critical `0.90`, auto-compact at `0.50`; answer reserve `4000` tokens.
- `max_files: 3`, `max_file_lines: 400`, `max_output_tokens: 8192`
  defaults.
- Per-call timeouts: `llm_timeout 120s`, `shell_exec_timeout 30s`,
  `test_timeout 60s`, `git_timeout 10s`, `lint_pass_timeout 15s`. The
  acceptance run-smoke reuses `shell_exec_timeout` (no new tunable).
- `auto_derive_acceptance` (default `True`) — gates the pre-loop
  acceptance-spec derivation (one narrow-pass LLM call per acceptance-less
  task at `/go`, mirroring `auto_annotate_plan`); disable for a
  headless/hermetic run.
- Fork human-decision timers: optimist `120s`, yolo+critical `60s`.
- **No RAM / boot budget asserted by code — `[?]`.** Single-GPU VRAM is the
  real constraint behind the upstream model-swap, but no number is pinned;
  PM to confirm whether a VRAM/RAM ceiling should be stated.

## File layout (module map)

| Directory / module | Responsibility |
|---|---|
| `code_scalpel/cli.py` | `typer` entry: launch TUI (no subcommand) or `init` onboarding |
| `code_scalpel/__init__.py` | package init; `__version__` resolved from installed metadata (no hardcoded literal) |
| `code_scalpel/__main__.py` | `python -m code_scalpel` entry → `cli.app` |
| `code_scalpel/runtime.py` | **Composition channel**: owns session+llm+memory+agent; `stream/ask/code_with_retry/fork/flush_upstream`; the one path every entry point shares |
| `code_scalpel/agent.py` | **StepAgent** — the core engine (~2840 LOC): tool loop, `stream_ask`, `code_with_retry`, narrow passes, compaction, fork detection; `run_plan` is now a thin delegator to `PlanRunner` (strangled out — agent.py shrank ~450 lines) |
| `code_scalpel/plan_runner.py` | **PlanRunner** — the per-task `run_plan` execution loop strangled out of `agent.py` (re-hash/plan_modified, streak/threshold, auto-commit hook, callback timing); computes the `should_run_now` position signal (last not-done task) and threads it into `verify_task`; `StepAgent.run_plan` delegates `PlanRunner(self).run(...)` |
| `code_scalpel/plan_loading.py` | TASKS.json/TASKS.md load + per-iteration re-hash + skill annotation + pre-loop acceptance-intent derivation for the run loop (extracted alongside the strangle) |
| `code_scalpel/plan_post_checks.py` | post-task hooks for the run loop (auto-commit, plan annotation) extracted alongside the strangle |
| `code_scalpel/plan_verify.py` | per-task Definition-of-Done machine checks: `Files:` exist, `Test command:` exit-0, git HEAD advanced (all demoting), and **verification #4 `_verify_acceptance`** — the registry-resolved acceptance run-smoke that **demotes `done → failed` only when intent (`applicable`) × position (`should_run_now`) × state (failing run-smoke) all agree, else records/surfaces only** (v0.14; see the Acceptance gate enforcement decision) |
| `code_scalpel/config.py` | pydantic config (`AppConfig`/`AgentConfig`/`ModelProfile`/`ModeTemperatures`), layered YAML loader, context autodetect |
| `code_scalpel/classifier.py` | pure keyword heuristic → `TaskType` (question/design/implement/debug/refactor/new_project) |
| `code_scalpel/policy.py` | trust-level decisions + hard-block command patterns (`decide`, `auto_confirm`) |
| `code_scalpel/session.py` | per-turn token/cost accounting, `prepare_turn`, compact baselines |
| `code_scalpel/state.py` | `AgentState` — `STATE.json` atomic persist/load for full resume; holds the `last_acceptance_command`/`_verdict`/`_reason` run-smoke fields (default-valued, forward-compatible) |
| `code_scalpel/memory.py` | `MemoryStore` — sqlite+FTS5 project notes (`/remember`, `/recall`, auto-recall) |
| `code_scalpel/recipes.py` | load `/learn`-generated recipes (eager/lazy) into context |
| `code_scalpel/learn.py` | `/learn` — generate recipe/skill markdown from model knowledge or a URL |
| `code_scalpel/fetch.py` | fetch + markdownify a URL for `/learn --url` |
| `code_scalpel/plan.py` | `Task` model, `TASKS.json`/`TASKS.md` parse + render |
| `code_scalpel/fork.py` | Fork API: `ForkOption/ForkResolution`, `HumanForker`/`LocalMetaForker`/`UpstreamForker`/`ReviewedAutoForker`, `detect_forks` |
| `code_scalpel/upstream_queue.py` | pending-fork batch queue + flush outcomes for upstream review |
| `code_scalpel/narrow_pass.py` | `NarrowPass`/`PassResult` — one-shot role-specialised LLM call |
| `code_scalpel/context_compress.py` | history → summary compaction |
| `code_scalpel/context_report.py` | `/context` budget breakdown by category |
| `code_scalpel/project_map.py` | navigation-style project map (overview + per-file drilldown) — render shim over `index/` |
| `code_scalpel/diagrams.py` | extract ```mermaid``` blocks from replies |
| `code_scalpel/clipboard.py` | copy card output to clipboard |
| `code_scalpel/jobs.py` | background job tracking (`/jobs`, jobs bar/modal) |
| `code_scalpel/i18n.py` | UI locale loader (strings live in `locale/`) |
| `code_scalpel/locale/` | UI locale string files (`en.yaml`, `ru.yaml`) |
| `code_scalpel/workspace.py` | internal-package detection, workspace helpers |
| `code_scalpel/llm/` | LLM adapter layer: `adapter.py` (OpenAI-compatible chat/stream), `lmstudio_native.py` + `native_events.py` (LM Studio native API), `lmstudio_status.py`/`lmstudio_swap.py` (model load/unload/swap), `cancel.py` (ESC cancellation) |
| `code_scalpel/index/` | tree-sitter symbol index: `parser.py`, `walkers.py`, `signatures.py`, `shape.py`, `builder.py`, `model.py`, `retrieve.py` (BM25), `__init__.py` |
| `code_scalpel/tools/` | agent tool surface: `agent_tools.py` (dispatch + JSON schemas), `files.py`, `git.py`, `search.py`, `shell.py`, `sandbox.py` (bwrap), `web_search.py` |
| `code_scalpel/checks/` | machine checks: `lint_pass.py`, `import_graph.py`, `empty_tests.py`, `syntax_check.py` |
| `code_scalpel/skills/` | per-stack test/lint/format contracts + the ProjectAdapter superset: `base.py` (`Skill` ABC + `ScaffoldSpec` + `provides_acceptance`/`bind`), `registry.py` (+ `acceptance_adapter(root)` selector), `python_skill.py`, `js_skill.py`, `go_skill.py`, `docker_skill.py`, `postgres_skill.py`, `sqlite_skill.py`, `python_cli_adapter.py` (first `ProjectAdapter`, `hidden`, `provides_acceptance=True`, root-binding `bind`), `python_pkg.py` (`resolve_pkg` — deterministic `python -m <pkg>` resolution, src-layout/hatchling only) |
| `code_scalpel/patch/` | `edit_block.py` — SEARCH/REPLACE parse + apply (fallback patch engine) |
| `code_scalpel/mermaid/` | mermaid parse + ASCII layout/render (`parser.py`, `layout.py`, `render.py`, `classes.py`, `sequence.py`) |
| `code_scalpel/prompts/` | all model-facing prompts as `.md` (system, mode_*, narrow passes, `retry/*`, `skills/*`, `derive_acceptance.md` — intent-judging acceptance-spec derivation); `__init__.py` is the single loader |
| `code_scalpel/recipes/` | bundled built-in recipes (ships with package) |
| `code_scalpel/tui/` | Textual app: `app.py` (~2129 LOC composition root + slash/keybindings), `widgets/` (input, footer, output, cards/*, plan_card, mermaid_card, jobs_*, tool_*) |
| `tests/` | test suite; mocks in `tests/mocks.py`; LLM tests gated by `@pytest.mark.llm` |

## Integration contract

- **Install (user):** `pip install code-scalpel` (PyPI), or a standalone
  Linux binary / `.deb` from a GitHub release.
- **Install (from source / dev):** `pip install -e .`, or
  `pip install -e ".[dev]"` for the toolchain; optional `[diagrams]`
  extra (also needs `npm i -g @mermaid-js/mermaid-cli`); `[build]` for
  the PyInstaller binary.
- **Entry points:** `code-scalpel` (launch TUI in cwd or `--path <dir>`);
  `code-scalpel init [--path --force]` (writes `.code-scalpel/config.yaml`
  + `.gitignore`); `code-scalpel --version`; `python -m code_scalpel`.
- **LLM endpoint contract:** any OpenAI-compatible `/v1` endpoint. Adapter
  uses chat completions + streaming + native function-calling
  (`tools=[...]` JSON Schema). Context window auto-detected via
  `GET /v1/models` `context_length` (LM Studio also exposes loaded context
  via its native API); falls back to `profiles.*.context_tokens`.
  **Streaming tool calls arrive fragmented and must be accumulated by
  `index`; native tool support is model-dependent** (`docs/stack-notes.md`
  LLM-transport entry).
- **LM Studio native surface:** model load/unload/swap and native
  streaming events via the `lmstudio` SDK (`lmstudio_native.py`,
  `lmstudio_swap.py`, `lmstudio_status.py`) — used for the upstream
  model-swap on single-GPU hosts; guarded behind LM-Studio backend
  detection (other OpenAI-compatible backends do not implement it).
- **Config paths (low→high priority):**
  `~/.config/code-scalpel/config.yaml` → `.code-scalpel/config.yaml`
  (project overrides, only explicit keys) → env / `.env` (secrets, highest).
- **On-disk project state (under `<cwd>/.code-scalpel/`):** `config.yaml`,
  `STATE.json`, `TASKS.json` + `TASKS.md`, `INDEX.json`, `memory.db`,
  `recipes/`, `skills/`, `LAST_COMPACT.md`, `chat.jsonl` (LLM log).
- **External CLIs consumed:** `git`, `rg` (ripgrep, pure-Python fallback),
  `ruff`/`mypy` (lint pass, when on PATH), `bwrap` (sandbox, when
  `sandbox: auto|on`), `mmdc` (mermaid render, optional).
- **Secrets env contract:** `OPENROUTER_API_KEY`, `OPENAI_API_KEY`,
  `LMSTUDIO_API_KEY`.

## Behavioral contract (taxonomies & invariants)

### Agent modes (`_AGENT_MODES`)

`ask` · `plan` · `code` · `review`. Cycled with Ctrl+T. `learn` and
`debug` exist as sub-flows (`/learn`, `/mode debug`), not in the cycle.
- **ask** — conversational, reads index/map/grep, never modifies code.
- **plan** — builds `TASKS.md`/`TASKS.json`, asks questions, runs fork
  detection; no execution.
- **code** — single supervised patch step (propose → confirm → apply →
  test).
- **review** — reads files/diff, returns structured review
  (Summary / Issues `[bug][risk][design][nit]` with `file:line` /
  Suggestions); SEARCH/REPLACE blocks forbidden in this mode.

### Trust levels (`policy.TrustLevel`)

One knob (Ctrl+L, `[skp]/[opt]/[ylo]` in footer) gates BOTH shell_exec and
patch-apply. Unknown value coerces to `skeptic`.

| Level | shell_exec / patch | Hard blocks | Fork resolution |
|---|---|---|---|
| `skeptic` (default) | every call needs UI confirm; refused if no UI handler | enforced | human ChoiceCard, no timer |
| `optimist` | auto-apply | enforced | human ChoiceCard, 120s countdown → Auto |
| `yolo` | auto-apply, no filtering | **none** | Auto immediately, except `critical=True` → 60s human window |

Hard-blocks (refused at skeptic+optimist, regex on raw command):
`rm -rf` on absolute/home/parent, block-device writes, `mkfs`/`mkswap`,
`sudo`/`su`/`doas`, pipe-to-shell, fork bomb, `cd`/`pushd` outside project,
redirect-write to absolute path, `cp`/`mv`/`install`/`rsync` out of project.

### Task classification (`classifier.TaskType`)

Pure keyword heuristic, word-boundary regex, first rule wins:
`debug` → `question` → `refactor` → `implement` (→ `design` when task
≥ 60 chars). Default `design`. Values: `question`, `design`, `implement`,
`debug`, `refactor`, `new_project`.

### Task outcome status (`run_plan`)

`done` · `failed` · `skipped` · (`noop_done` proposed, not landed
`(inferred)`). `skipped` is a stop reason — the model must perform a task.
Per-task git HEAD must advance (sha ≠ prev) or the task is `failed`;
auto-commit hook commits `<task.id>: <task.title>` if the model forgot.
**A 4th machine check (acceptance run-smoke, verification #4) also runs and,
since v0.14 (`feat/acceptance-spec-in-tasks`), ENFORCES — it demotes
`done → failed` — but ONLY when three signals agree** (intent × position ×
state): the spec is *applicable* (a derived spec judged from task text to be
a runnable CLI deliverable; the default-floor never is), the task is the
*last not-done task* (`should_run_now`, the position the deliverable should
be runnable end-to-end), and the deterministic run-smoke *fails*. **An early
not-built-yet task of a CLI plan, a library, and a no-spec project are all
observed, never demoted.** **The taxonomy is unchanged** — no new status;
enforcement reuses the existing `done → failed` edge. Everywhere the three
signals do not all agree the run-smoke is still recorded/surfaced and never
demotes. The run-smoke verdict (`passed`/`failed`/`noop`) is also a distinct
`AgentState` field. See the *Acceptance gate enforcement* decision in
`## Architectural decisions` and `## State model`.

### Tool surface (function-calling schemas)

`read_file` (whole/window/find modes) · `write_file`
(overwrite/replace_lines/insert_after_line) · `project_map` (tree /
per-file outline; legacy aliases `list_files`, `map_file`) ·
`goto_definition` · `find_references` · `grep` · `retrieve` (BM25) ·
`run_tests` · `run_python` · `shell_exec` · `web_search` · `web_learn` ·
`load_skill` / `unload_skill`. Dispatch (`tools/agent_tools.execute`)
never raises — always returns a `ToolResult(ok=…)`.

### Step phases (`state.StepPhase`)

`idle` · `generating` · `reviewing` · `applying` · `testing`. Persisted in
`STATE.json` with `dirty_patch` for crash recovery.

### Recipe / skill loading

Recipes load **eager** (every turn) or **lazy** (only when task text
contains a keyword, case-insensitive substring). Discovery priority:
project `.code-scalpel/recipes/` → user `~/.config/...` → bundled. Skills
are language skills (own test runner: Python/JS/Go) vs component skills
(Postgres/SQLite, detect-only) vs `MarkdownSkill` (advisory, load-only).

### Fork resolution paths

A `fork()` carries `ForkOption`s; a `ForkResolution` is returned by one of:
`HumanForker` (ChoiceCard), `LocalMetaForker` (same local model in an
architect role), `UpstreamForker` (stronger batched model), or
`ReviewedAutoForker` (auto-pick recorded for later override review). The
resolver is selected by trust (see the trust table). The native LM Studio
path resolves forks via `json_schema` structured output and **ignores
`tool_call.*` events** on that path `(inferred)` — the native path is used
for json_schema fork resolution, not for tool loops.

### System invariants

- **Single channel:** every model turn goes through
  `Session.prepare_turn` → `StepAgent.stream_ask` — see `## Architectural
  constraints`.
- **Project containment:** subprocess cwd pinned to root + `policy.py`
  hard blocks — enforced by `SC1`/`SC2` (`## Security constraints`).
- **Path containment:** file tool paths resolve under the project root
  including symlinks — enforced by `SC4`.
- **Secrets isolation:** API keys never reach YAML, logs, or model context
  — enforced by `SC5`.
- **Atomic on-disk state:** `STATE.json` and `TASKS.md` write `.tmp` →
  `os.replace` (atomic on POSIX); `run_plan` re-hashes `TASKS.md` each
  iteration and stops on `plan_modified` — stated inline above and in
  `## State model`.
- **Dispatch never raises:** the tool boundary returns a `ToolResult`,
  never an exception — stated inline above (tool surface).
- **Acceptance enforcement is three-signal-gated (v0.14):** verification
  #4 demotes `done → failed` only when intent (`applicable`) × position
  (`should_run_now`, the last not-done task) × state (failing run-smoke)
  all agree; an early not-built-yet CLI task, a library/no-spec project, and
  the default-floor are all observed, never demoted (the feature-2
  no-regression lock plus the greenfield early-task lock) — stated inline
  above (task outcome status) and in `## State model`. Model-derived
  acceptance is args-only — enforced by `SC7` (`## Security constraints`).
- **Endpoint reachability:** the *First-time setup* journey requires a
  reachable LLM endpoint before any turn produces output (see
  `docs/user-journeys.md`).
- **Per-task HEAD advance:** the *Run the plan* journey requires git HEAD
  to advance per task or the task is `failed` (see
  `docs/user-journeys.md`).

## State model

Two state machines exist; both reference their value sets from
`## Behavioral contract` (the enum owns the states). New here are the
edges/triggers.

**Plan execution (`run_plan`), per task** — status enum owned by
`### Task outcome status`:

| State | Allowed transitions → | Trigger / event | Notes |
|---|---|---|---|
| (pending) | `done`, `failed`, `skipped` | task dispatched through `code_with_retry` | initial |
| `done` | — | tests pass + git HEAD advanced (or auto-commit hook commits) | terminal success; marked `[✓]` in TASKS.md |
| `failed` | — | tests fail / HEAD didn't move / verify fails; ≥ `stop_after_failures` consecutive → stop "max_failures" | net-new files kept on disk for inspection |
| `skipped` | — | model skipped a required task | stop reason — not allowed silently |

**Acceptance run-smoke verdict (per task):** a separate field set on
`AgentState` (`last_acceptance_verdict`): `passed` (run-smoke exit 0, and
the non-empty `expected` observable present) · `failed` (non-zero exit /
`timeout` / `pkg-unresolvable` / `malformed-args`, reason persisted) ·
`noop` (no acceptance adapter detected the project type) · `unknown`
(default, never recorded). A `noop` never clobbers a prior
`passed`/`failed`. **Since v0.14 this verdict drives the `done → failed`
edge above ONLY when three signals agree** — intent (`spec.applicable`,
a derived-and-applicable CLI spec judged from task text), position
(`should_run_now`, the structurally last not-done task), and a *failing*
state (the run-smoke): `applicable AND should_run_now AND not run_smoke_ok`
demotes. An **early not-built-yet** task of a CLI plan (`should_run_now`
False), a **library / not-applicable** spec, and the **default-floor** are
all recorded/surfaced only — they drive no edge, exactly as in feature 2.
The intent (`applicable`) is derived once pre-loop from task text and
written back (stable on resume/re-run, and correct on a greenfield/empty
repo); the position is recomputed deterministically in the run-loop; the
state is the deterministic verify-time run-smoke. **Known limitation:**
position is proxied by "last not-done task", so a plan whose final task is
non-CLI observes rather than enforces (safe under-enforcement) — see the
*Acceptance gate enforcement* decision.

Loop-level stops: `all_done`, `no_tasks`, `plan_modified` (TASKS.md hash
changed mid-run), `CancelledError` (ESC — already-marked tasks stay).

**Patch step (`code_with_retry`)** — phase enum owned by `### Step
phases`: `generating → reviewing → applying → testing`; a failed
`run_tests` triggers `debug_pass` (max 2 attempts, hypothesis/test-output
equality stop) then a retry prompt; rollback via the snapshot path on
cancel.

## Release flow

- Versions live in `pyproject.toml` only (`version = "0.12.5.dev0"` in
  tree). `code_scalpel.__version__` is resolved from installed package
  metadata via `importlib.metadata` — no hardcoded version literal in code.
- Open a version: PR `chore/open-v0.X` bumps to `0.X.0.dev0`.
- Close a version: all roadmap items `✓` → PR `chore/release-v0.X` bumps
  to `0.X.0` and strikes the §31 heading; then `git tag v0.X.0 &&
  git push --tags`.
- Branches: `feat/` `fix/` `chore/` `docs/`; `main` protected, PR-only,
  no force-push. Default merge = merge commit (squash only for messy
  branches).
- **CI (`.github/workflows/ci.yml`):** on push to `main` and on PR, runs
  `ruff check .`, `ruff format --check .`, `mypy code_scalpel/`, and
  `pytest -q` across Python 3.11 and 3.12. The live-LLM tests
  (`@pytest.mark.llm`, `--run-llm`) are **not** run in CI (slow,
  non-deterministic, need LM Studio).
- **Release CI (`.github/workflows/release.yml`):** on a `v*` tag push,
  builds a standalone PyInstaller binary + a `.deb` (via `nfpm`) and
  attaches them to the GitHub Release (auto-generated notes). On PRs that
  touch build infra it runs a no-attach smoke build.
- **Outcome release-gate is N/A as an automated gate today.** The
  end-to-end probe (`notes_cli`, N≥3 to `task_solved`) is the *aspirational*
  release signal but is run **manually**; it is not wired as a required CI
  check (v0.13 backlog `(inferred)`). The `notes_cli` 3/3 teeth move to
  feature 4 (`feat/acceptance-spec-in-tasks`), where the acceptance gate
  can demote on a CLI deliverable at the plan's final step.

## Security constraints

> Enforceable rules; referenced by `SCn` from `docs/threat-model.md`.

- **SC1** — Model-issued shell commands pass `policy.decide(cmd, trust)`;
  hard-block patterns are refused at skeptic+optimist regardless of user
  approval; skeptic requires an explicit UI confirm callback (refused if
  absent).
- **SC2** — Subprocess cwd is pinned to the project root; `cd`/redirect/
  copy-out patterns that would write outside it are hard-blocked even
  without the sandbox.
- **SC3** — `shell_exec`/`run_python` run inside a `bwrap` sandbox when
  `sandbox: auto|on`: project RW, `/usr`/`/lib`/`/etc` RO, `/home`+`/tmp`
  as tmpfs, network shared. **Requires unprivileged user namespaces;** on
  Ubuntu 23.10+/24.04 (`apparmor_restrict_unprivileged_userns=1`) bwrap
  fails out of the box — the tool must detect the failure and degrade to
  policy-only, not crash (`docs/stack-notes.md` bwrap entry).
- **SC4** — File tool paths are validated to resolve under the project
  root (`_is_inside_project` resolves symlinks before access).
- **SC5** — API keys are read only from env/`.env`, never written to YAML,
  never echoed into model context or logs.
- **SC6** — `write_file` rejects empty `content`; `mkdir` bare-form is a
  no-op (write_file creates parents) to keep model file ops on the
  canonical path.
- **SC7** — Model-derived acceptance input is **args-only**: the
  acceptance-spec narrow pass may supply only subcommand args + an expected
  substring, never a free-form shell command. Argv assembly is
  **adapter-owned** (`run_smoke(args)` builds `python -m <pkg> <args>`),
  tokenized via `shlex`, so model-supplied metacharacters become literal
  argv tokens, never shell operators; execution stays on the SC1/SC2/SC3
  gated `execute()` path. (Referenced by `docs/threat-model.md` T12.)

### Recovery & key-loss posture

code-scalpel is a local tool with nothing server-side to recover. There is
no account, no secret store, and no hosted state. An API key is relevant
only when a remote OpenAI-compatible endpoint (e.g. OpenRouter) is used and
lives solely in the user's `.env` (consistent with SC5); the default local
LM Studio backend needs no key at all. Consequences of loss:

- **Lost key** — re-issue it at the provider and put it back in `.env`;
  nothing in code-scalpel stored or wrapped it.
- **Lost device / access** — restore the repository from git like any local
  tool. Session/crash continuity within a machine is covered by `STATE.json`
  + `memory.db` (see State model), but cross-device access recovery is
  explicitly **not the product's responsibility**.

## Code conventions

### AI-specific minimums

Stated convention (target numbers, single-sourced here):

- Max source file: 300 lines
- Max function / method: 50 lines
- Cyclomatic complexity: max 10 per function
- No file-level lint suppressions (only line- or function-level with comment)
- New code test coverage: min 80%

**Enforcement status — convention + AI-review backstopped, NOT
ruff-enforced today.** The live ruff `lint.select` is
`["E","F","I","UP","B","SIM"]` (`E501` ignored) and excludes the `PLR*`
(too-many-statements/branches/returns/args/locals) and `C901` (mccabe
complexity) families that would encode these numbers — so every minimum
above is currently AI-self-policed, not linter-blocked. Several legacy
modules already exceed the file ceiling (`agent.py` ~2840 lines,
`tui/app.py` ~2129 lines, `tools/agent_tools.py`, `fork.py`). The
`run_plan` strangle (v0.14) cut `agent.py` from ~3289 to ~2840 lines and
the extracted run-loop modules (`plan_runner.py`, `plan_loading.py`,
`plan_post_checks.py`, `plan_verify.py`) are each within the file ceiling.
**ruff cannot express max-lines-per-file or copy-paste detection at all**
— those stay AI-review-backstopped (smell/hygiene review type) regardless
of config.

**Gradual enable path (mapped, not prescribed — `docs/stack-notes.md`
AI-minimums→ruff mapping).** Turning `PLR*`/`C901` on now would fail lint
on the oversized legacy modules. A clean path, if the maintainer chooses
to enforce: add the families to `lint.select` **plus**
`[tool.ruff.lint.per-file-ignores]` carving out the known-oversized
modules, then shrink that ignore list as modules are refactored; **or**
gate the rules on new/changed code only, leaving legacy untouched. The
target numbers live here; the rule-by-rule carrier mapping lives in
`docs/stack-notes.md`.

### Stack-specific rules

- Python 3.11+, async for all I/O; never block the event loop in an async
  path; let `CancelledError` (ESC) propagate after cleanup.
- DI through the constructor; `Runtime` / TUI `app.py` is the only
  composition root.
- All public functions/methods annotated; `mypy --strict` clean over
  `code_scalpel/`.
- No magic numbers — tunables in `config.py` (pydantic v2:
  `model_validate`/`model_dump`, `ConfigDict`, `@field_validator`).
- Comments only when WHY is non-obvious.
- Prompts live as `.md` files in `code_scalpel/prompts/`, loaded once via
  `prompts/__init__.py`.
- Component-specific idioms (Textual workers, httpx redirects/timeouts,
  FTS5 query escaping, tree-sitter ABI, bwrap composition) — see
  `docs/stack-notes.md`.

### Linter commands

```
ruff check . && ruff format --check .
ruff check --fix . && ruff format .
mypy code_scalpel/
pytest -x          # pytest --run-llm to include live-LLM tests
```

## Dependencies

### Policy

Prefer the standard library; reject deps that don't pull their weight
(mem0ai rejected after a spike — +138 MB, broken dedup, LM Studio
incompatibility — replaced by a ~166-LOC sqlite+FTS5 module).

### Current dependencies

| Package | Purpose | Added |
|---|---|---|
| `textual` + `textual-autocomplete` | TUI framework + slash completion | v0.1 |
| `typer` / `click` | CLI | v0.1 |
| `pydantic` v2 + `pyyaml` | config schema + files | v0.1 |
| `python-dotenv` | secrets from `.env` | v0.1 |
| `openai` (`AsyncOpenAI`) | LLM transport | v0.1 |
| `lmstudio` (`>=1.5`) | LM Studio native surface (load/unload/swap) | (native swap era) |
| `unidiff` | diff parsing (display only) | v0.1 |
| `pathspec` | `.gitignore`-aware listing | v0.1 |
| `httpx` + `html2text` | URL fetch + markdownify | v0.3 |
| `tree-sitter` + `tree-sitter-python` | Python symbol index (`ast` fallback elsewhere) | v0.3 |
| `ruff` / `mypy` / `pytest` / `pytest-asyncio` / `pytest-cov` / `hatchling` | dev toolchain | v0.1 |
| `rich-pixels` (optional `[diagrams]`) + npm `@mermaid-js/mermaid-cli` | mermaid render | optional |
| `pyinstaller` (optional `[build]`) | standalone binary | `[build]` |
