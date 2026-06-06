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
  ~3289 lines, `tui/app.py` ~2129 lines).

## Operational limits & budgets

- Typical target project: **10–100 files, 100–500 lines/file**, model
  context window **16k–32k tokens**, local LLM **7B–14B** (`plan.md` §2).
- Context budget thresholds (config, fraction of window): warn `0.70`,
  critical `0.90`, auto-compact at `0.50`; answer reserve `4000` tokens.
- `max_files: 3`, `max_file_lines: 400`, `max_output_tokens: 8192`
  defaults.
- Per-call timeouts: `llm_timeout 120s`, `shell_exec_timeout 30s`,
  `test_timeout 60s`, `git_timeout 10s`, `lint_pass_timeout 15s`.
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
| `code_scalpel/agent.py` | **StepAgent** — the core engine (~3289 LOC): tool loop, `stream_ask`, `code_with_retry`, `run_plan`, narrow passes, compaction, fork detection, plan execution |
| `code_scalpel/config.py` | pydantic config (`AppConfig`/`AgentConfig`/`ModelProfile`/`ModeTemperatures`), layered YAML loader, context autodetect |
| `code_scalpel/classifier.py` | pure keyword heuristic → `TaskType` (question/design/implement/debug/refactor/new_project) |
| `code_scalpel/policy.py` | trust-level decisions + hard-block command patterns (`decide`, `auto_confirm`) |
| `code_scalpel/session.py` | per-turn token/cost accounting, `prepare_turn`, compact baselines |
| `code_scalpel/state.py` | `AgentState` — `STATE.json` atomic persist/load for full resume |
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
| `code_scalpel/skills/` | per-stack test/lint/format contracts: `base.py` ABC, `registry.py`, `python_skill.py`, `js_skill.py`, `go_skill.py`, `docker_skill.py`, `postgres_skill.py`, `sqlite_skill.py` |
| `code_scalpel/patch/` | `edit_block.py` — SEARCH/REPLACE parse + apply (fallback patch engine) |
| `code_scalpel/mermaid/` | mermaid parse + ASCII layout/render (`parser.py`, `layout.py`, `render.py`, `classes.py`, `sequence.py`) |
| `code_scalpel/prompts/` | all model-facing prompts as `.md` (system, mode_*, narrow passes, `retry/*`, `skills/*`); `__init__.py` is the single loader |
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
  check (v0.13 backlog `(inferred)`).

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
modules already exceed the file ceiling (`agent.py` ~3289 lines,
`tui/app.py` ~2129 lines, `tools/agent_tools.py`, `fork.py`).
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
