# code-scalpel

## Project

**What:** A terminal (Textual TUI) coding agent that makes *weak local LLMs* (default qwen2.5-coder-14b in LM Studio) do reliable, reviewable code work on a developer's own repository.

**Who:** A solo developer working on their own code through a local LLM — someone who wants small, controllable, testable changes rather than a fully autonomous programmer.

**Problem solved:** Weak local models fail at large-context, large-diff agentic coding. code-scalpel works around their limits: small context, small patches (explicit `write_file`, not unified diff), many narrow single-role passes instead of one fat prompt, machine checks over prompt instructions, and trust-gated autonomy.

**Core principle:** small context, small patch, fast test, controlled autonomy.

## Project kind: software

**Language canon:** Conversation language: the user's (Russian). Artifacts (files, code, commits, agent-authored docs): English.

> Note: `docs/plan.md` and `docs/article_draft.md` are pre-existing bilingual/Russian authored documents — they keep their language. New protocol artifacts (architecture.md, product.md, contracts, plans, reviews) are English.

---

## Architecture

### Tech stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.11+, asyncio | Async everywhere there is I/O; broad ecosystem for LLM/CLI tooling |
| TUI / CLI | Textual + Typer/Click + textual-autocomplete | Rich terminal UI; ergonomic command surface |
| Config | Pydantic v2 + PyYAML + python-dotenv | Typed config, no magic numbers; secrets via env |
| LLM transport | openai SDK / AsyncOpenAI + `lmstudio` SDK | OpenAI-compatible endpoints (LM Studio default, llama.cpp, OpenRouter, vLLM, Ollama) |
| Code intelligence | tree-sitter (+ `ast` fallback), pathspec | Symbol index; .gitignore semantics |
| Patch engine | custom SEARCH/REPLACE blocks (unidiff parse-only) | Small, exact-match patches that weak models can emit reliably |
| Data / fetch | httpx, sqlite3 + FTS5 | URL/web fetch; project memory store |
| Shell / exec | subprocess → git/ripgrep, bubblewrap (`bwrap`) | Sandboxed shell; ripgrep with pure-Python fallback |
| Optional | @mermaid-js/mermaid-cli, rich-pixels | Diagram render (`[diagrams]` extra) |
| Build | hatchling | Package + `.deb` release |

Target platform: **Linux** (bwrap dependency, Linux binary + `.deb` release).

### Architectural constraints
Agents must not violate these without an explicit PM decision:

- **Small context, small patch.** Prefer narrow single-role LLM passes over one fat prompt. Patches are explicit `write_file` / SEARCH-REPLACE blocks, never unified diffs.
- **Async for all I/O.** Blocking I/O on the event loop is a bug.
- **DI through the constructor.** The composition root is the single place wiring is assembled — no service locators, no hidden globals.
- **No magic numbers — everything in config** (`config.py` + pydantic).
- **Machine checks over prompt instructions.** Where a property can be verified mechanically, verify it; don't rely on the model obeying the prompt.
- **This is NOT an autonomous-programmer / Claude-Code replacement.** Autonomy is trust-gated (skeptic / optimist / yolo) and bounded.

### Security constraints

See `docs/threat-model.md`. Key surfaces: the agent runs shell commands and applies patches from LLM output. The `bwrap` sandbox is the execution boundary (Linux userns); autonomy levels gate whether the model may run shell, apply patches, and auto-resolve forks. Fetched URL/web content is currently inserted without sanitisation — prompt-injection is an open risk (`[?]`, see threat-model T08).

### Code conventions
AI-specific minimums (target — see `docs/architecture.md` `### AI-specific minimums` for the canonical numbers):

- Max file length: 300 lines · Max function length: 50 lines · Cyclomatic complexity: max 10 · No file-level lint suppressions · Test coverage: min 80% for new code.

**Enforcement status:** these are currently **convention + AI-review backstopped, NOT ruff-enforced.** The live `ruff` config does not enable the `PLR*` / `C901` families, and several legacy modules exceed the limits (`agent.py` ~3289 lines, `tui/app.py` ~2129). Turning the rules on now would fail lint on legacy files. New code is held to the minimums by review; a gradual ruff path (per-file-ignores / new-code-only gating) is documented in `docs/stack-notes.md`.

Comment restraint:
- Comment WHY-when-non-obvious only. Do NOT comment WHAT — well-named code says that.
- Rationale lives in the plan / arch / contract / test, not inline. No inline rule-ID citations.
- All public functions and methods must have type annotations (`mypy --strict`).

---

## Pipeline

Every command in this block must be green before coder is done. No exceptions.

**Tests + lint:**
```
pytest
ruff check .
ruff format --check .
mypy code_scalpel/
```

Notes:
- `ruff format` is the formatter (not black). Run `ruff check --fix . && ruff format .` to autofix.
- Tests live in `tests/`; they mock the LLM and shell via `MockLLMAdapter` / `MockShellRunner` in `tests/mocks.py`.
- **Tests are written with the code, not after.** Every commit introducing a module includes its test. No test — no commit.
- `pytest --run-llm` (live LM Studio, `@pytest.mark.llm`) is **opt-in**, not a default gate — slow and non-deterministic.
- The `<lint command>` does not yet enforce the AI-specific minimums (see Code conventions above) — they are review-backstopped pending the gradual ruff path in `docs/stack-notes.md`.

**Validators** (from `pm-stack-researcher`; see `docs/stack-notes.md` "Validators wired into pipeline"):
```
mypy code_scalpel/        # strict-mode type check = spec-compliance gate
```

---

@.ai-pm/tooling/WORKFLOW.md

---

## Project-specific working rules

These predate the protocol and remain in force alongside it.

### Working with the plan (`docs/plan.md`)

`docs/plan.md` is the long-standing living design document (architecture + roadmap §31, ~3900 lines). It remains the project's narrative source of truth for design intent. When implementing:
- If something in the plan is wrong — **fix the plan first, then write code.**
- If an architectural decision is made that isn't in the plan — add it.
- Don't add features beyond what the current roadmap version describes.
- Mark progress with `✓` inline in the plan next to the item — what was done and why (context for future sessions). When a whole version closes, strike its `### vX.Y` heading and add the date.

Current version: **v0.14 open** (`pyproject.toml` = `0.12.5.dev0`). v0.1–v0.13 closed (see `docs/plan.md` §31).

> The protocol's feature pipeline (`/pm-plan` → coder → review → `pr-prep`) is now the path for new work. The plan.md roadmap and the protocol's `docs/features/` plans coexist: plan.md carries the long-range narrative; each protocol feature gets its own `docs/features/<topic>_plan.md` + contract.

### The article (`docs/article_draft.md`)

A draft technical article about how the system was designed. Append a paragraph (don't rewrite) when: a non-trivial architectural decision is made, something had to be redone, or something interesting is found about qwen14b's behaviour with patches.

### Test model

qwen2.5-coder-14b-instruct in LM Studio (`http://localhost:1234/v1`) — LM Studio must be running when testing the agent live. Cross-model bench in `docs/bench-models.md` (7 models, 24 tests): gemma-4-26b-a4b = 100% quality but 2.5× slower; qwen3.5-9b = 79%, low-RAM fallback; coder-14b stays default as the Pareto optimum.

### Versioning & branches

`pyproject.toml` `version` is the single source. The protocol owns the git/PR flow (one branch per PR, `pr-prep`, merge on GitHub). Project version convention from plan.md §31: open `v0.X` → `0.X.0.dev0`; close → `0.X.0`, tag `v0.X.0`, GitHub release with changelog.

---

## Docs

| File | Purpose |
|---|---|
| `docs/product.md` | **Product front door** — authored PM funnel, owned by `pm-architect`, PM-validated. Not generated |
| `docs/product-map.md` | **Capability map** — contract-centric, PM-facing, auto-generated |
| `docs/architecture.md` | Stack, decisions, constraints |
| `docs/user-journeys.md` | Existing user scenarios |
| `docs/stack-notes.md` | Stack idioms, constraints, validators, integration contracts |
| `docs/features/` | Per-feature plans (protocol pipeline) |
| `docs/ui-guide.md` | TUI conventions |
| `docs/threat-model.md` | Security model (shell exec, patch apply, sandbox) |
| `docs/plan.md` | Long-range design narrative + roadmap §31 (pre-protocol, source of truth for intent) |
| `docs/article_draft.md` | Technical article draft (appended alongside code) |
| `DEVELOPING.md` | Contributor stack, configs, commands |
