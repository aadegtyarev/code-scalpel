# Stack notes

Living document. Initialised at bootstrap, extended on every feature that touches a new external system.
Maintained by `pm-stack-researcher`. Read by `pm-plan`, `pm-architect`, `pm-coder`, `pm-plan-checker`.

**Last full review:** 2026-06-06

---

## How this document is used

- **pm-plan** reads it before drafting a plan that touches any listed component. If the feature touches a component that is missing here, `/pm-plan` spawns `pm-stack-researcher` to extend this document **before** continuing.
- **pm-architect** reads it when proposing variants — stack constraints are part of the trade-off space.
- **pm-coder** reads it before writing a mapping, handler, schema, or any integration code for a listed component. On contradiction between task and stack-notes, coder stops and escalates — no fallback to WebSearch.
- **pm-plan-checker** checks every diff against the relevant entries. Code that contradicts an idiom or constraint listed here is **blocking** with a citation back to this file.

If this document is missing or empty for a component the feature touches — that is a protocol-level defect, not a content gap.

**Confidence tags.** Load-bearing rules carry a tag on the source line: `confidence: doc-cited (unverified)` (confirmed from canonical docs, not exercised end-to-end on this project's config) or `confidence: execution-verified` (exercised on a real/throwaway target). All rules below start `doc-cited (unverified)`; only the orchestrator promotes after a spike. Untagged rules are treated as `doc-cited (unverified)` by convention.

---

## Platform filesystem layout

- **Target platform:** Standard Linux (primary). `bwrap` sandbox + `.deb`/standalone-binary release artifacts are Linux-only. Terminal/TUI app; no web or GUI. Runs in the user's project directory, not as a system service.
- **Partitions and survival rules:** N/A — standard Linux FHS, no partition survival rules. The app does not install into protected/overlay partitions; it is a user-space tool.
- **User-editable service configs must go to:** user config `~/.config/code-scalpel/config.yaml` (XDG) and per-project `<cwd>/.code-scalpel/config.yaml` — survives: yes (ordinary home/project files).
- **Read-only rootfs paths (wiped on flash):** N/A.
- **Persistent data partition:** the per-project `<cwd>/.code-scalpel/` directory holds `STATE.json`, `TASKS.json`/`TASKS.md`, `INDEX.json`, `memory.db`, `recipes/`, `skills/`, `LAST_COMPACT.md`, `chat.jsonl` — ordinary files in the user's project tree.
- **Source:** `docs/architecture.md` "Target platform" + "Integration contract" (internal — owner: project maintainer).
- **Last reviewed:** 2026-06-06

> **Reality check vs. task brief.** The live `pyproject.toml` (`version = "0.12.5.dev0"`) is the source of truth and differs from the bootstrap brief in load-bearing ways. Captured here so coders trust the file, not the brief:
> - **LLM transport** declares `openai>=1.30` **and** `lmstudio>=1.5` (the official LM Studio Python SDK), not openai alone. The native LM Studio surface (model load/unload/swap, native streaming) goes through `lmstudio`, not raw `/api/v0` HTTP.
> - **tree-sitter grammar packs:** only `tree-sitter-python~=0.25` is a declared dependency. JS/Go/Rust packs referenced in the design are **not** in `pyproject.toml` — treat non-Python tree-sitter index as aspirational / `ast`-fallback until a pack is added.
> - **`sqlite3` + FTS5, `subprocess`, `git`, `rg`, `bwrap`** are not Python dependencies — `sqlite3`/`subprocess` are stdlib; `git`/`rg`/`bwrap` are external CLIs consumed at runtime, not pip deps.
> - **No `unidiff`-based unified-diff *application*** — `unidiff>=0.7` is a declared dep used for diff *parsing*; patch *application* is the custom SEARCH/REPLACE engine in `code_scalpel/patch/edit_block.py`.
> - **`html2text>=2024.2.26`** is a declared dep (URL→markdown for `/learn --url`), not in the brief.
> - **Optional extras:** `[diagrams]` = `rich-pixels>=3.0` (renders the mermaid PNG as Unicode half-blocks; the PNG itself needs the npm `@mermaid-js/mermaid-cli` `mmdc` binary on PATH). `[build]` = `pyinstaller>=6.0`.
> - **ruff `lint.select` is `["E","F","I","UP","B","SIM"]` with `E501` ignored** — the Pylint-refactor (`PLR*`) and mccabe (`C901`) complexity families that would encode the AI-minimums are **NOT currently enabled**. See the AI-minimums mapping below.

---

## Components

### Python 3.11+ / asyncio

- **Role in this project:** Implementation language and concurrency model; async everywhere there is I/O (LLM calls, shell, HTTP overlap; ESC-cancellable streaming).
- **Canonical docs:** https://docs.python.org/3/library/asyncio.html
- **Spec / reference:** https://docs.python.org/3.11/whatsnew/3.11.html
- **Required validators:** (shared toolchain — see pipeline table) `mypy code_scalpel/`, `ruff check .`, `pytest`.
- **Idioms and constraints:**
  - `requires-python = ">=3.11"` — `StrEnum`, `X | None` union syntax, and `asyncio.TaskGroup` are available; do not gate them behind version checks. Source: `pyproject.toml` line 11; https://docs.python.org/3.11/whatsnew/3.11.html `confidence: doc-cited (unverified)`
  - Never block the event loop with a synchronous call in an async path; offload blocking work (subprocess wait, file I/O on hot paths) appropriately. Source: https://docs.python.org/3/library/asyncio-dev.html#running-blocking-code
  - `asyncio.CancelledError` propagates on cancel (ESC) and must be allowed to propagate after cleanup, not swallowed. Source: https://docs.python.org/3/library/asyncio-task.html#task-cancellation
- **Known gotchas:**
  - Awaiting inside a finally/cleanup block during cancellation can swallow the cancel; re-raise `CancelledError`. Source: https://docs.python.org/3/library/asyncio-task.html#task-cancellation
- **Last reviewed:** 2026-06-06

### Textual (TUI) + textual-autocomplete

- **Role in this project:** Async-native terminal UI; cards stream LLM tokens into widgets. `textual-autocomplete` powers slash-command completion.
- **Canonical docs:** https://textual.textualize.io/
- **Spec / reference:** https://textual.textualize.io/guide/workers/
- **Required validators:** none Textual-specific beyond the shared toolchain.
- **Idioms and constraints:**
  - Run background/long work with the Worker API — `@work` decorator or `run_worker()`; do not spawn bare `asyncio.create_task` for UI-affecting work. Source: https://textual.textualize.io/guide/workers/ `confidence: doc-cited (unverified)`
  - Use `@work(exclusive=True)` where ordering matters (network/LLM requests) so a new run cancels the previous and avoids races. Source: https://textual.textualize.io/guide/workers/ `confidence: doc-cited (unverified)`
  - **Async workers may update widgets directly**; **thread workers (`thread=True`) must use `App.call_from_thread()`** to touch the UI. Never call widget update methods directly from a thread worker. Source: https://textual.textualize.io/guide/workers/ `confidence: doc-cited (unverified)`
  - Never block the event loop with synchronous operations inside an async worker; use a thread worker for non-async libraries. Source: https://textual.textualize.io/guide/workers/
- **Known gotchas:**
  - Worker state machine is PENDING → RUNNING → (CANCELLED / ERROR / SUCCESS); a swallowed exception inside a worker surfaces as ERROR, not a crash — check worker results. Source: https://textual.textualize.io/guide/workers/
- **Last reviewed:** 2026-06-06

### Typer (on Click)

- **Role in this project:** CLI entry — `code-scalpel` launches the TUI (no subcommand); `code-scalpel init` onboarding; `--version`. Entry point `code_scalpel.cli:app` (`pyproject.toml` `[project.scripts]`).
- **Canonical docs:** https://typer.tiangolo.com/
- **Spec / reference:** https://typer.tiangolo.com/tutorial/commands/
- **Idioms and constraints:**
  - Commands are declared with `@app.command()`; a callback (`@app.callback()`) holds shared options and runs when no subcommand is given — this is how "bare `code-scalpel` launches TUI, `init` is a subcommand" is wired. Source: https://typer.tiangolo.com/tutorial/commands/callback/ `confidence: doc-cited (unverified)`
  - Typer is built on Click; Click context/exit-code conventions apply (`typer.Exit(code=...)` for non-zero exits). Source: https://typer.tiangolo.com/tutorial/terminating/
- **Known gotchas:**
  - Reading version via `importlib.metadata` (project rule: no `__version__` string in code) means the package must be installed (`pip install -e`) for `--version` to resolve. Source: https://docs.python.org/3/library/importlib.metadata.html
- **Last reviewed:** 2026-06-06

### Pydantic v2 + PyYAML + python-dotenv (config / secrets)

- **Role in this project:** Schema-validated layered config (`AppConfig`/`AgentConfig`/`ModelProfile`); YAML files; secrets from env/`.env` only.
- **Canonical docs:** https://docs.pydantic.dev/latest/
- **Spec / reference:** https://docs.pydantic.dev/latest/concepts/models/
- **Idioms and constraints (Pydantic v2 — `pydantic>=2.7`):**
  - Use `model_validate()` / `model_validate_json()`; the v1 `parse_obj()` / `parse_raw()` are deprecated. Source: https://docs.pydantic.dev/latest/concepts/models/ `confidence: doc-cited (unverified)`
  - Configure via `model_config = ConfigDict(...)`, not a nested `class Config`. `frozen=True` replaces `allow_mutation = False`. Source: https://docs.pydantic.dev/latest/concepts/models/ `confidence: doc-cited (unverified)`
  - Use `@field_validator` (was `@validator`) and `@model_validator` (was `@root_validator`). Source: https://docs.pydantic.dev/latest/concepts/validators/ `confidence: doc-cited (unverified)`
  - Serialize with `model_dump()` / `model_dump_json()`; v1 `.dict()` / `.json()` are deprecated. Source: https://docs.pydantic.dev/latest/concepts/serialization/
  - **API keys never go in YAML** — env / `.env` only (project rule SC5 + architecture "Secrets env contract": `OPENROUTER_API_KEY`, `OPENAI_API_KEY`, `LMSTUDIO_API_KEY`). Source: `docs/architecture.md` SC5.
- **Known gotchas:**
  - `yaml.safe_load` (never `yaml.load` without a Loader) for untrusted config files — `yaml.load` can execute arbitrary tags. Source: https://pyyaml.org/wiki/PyYAMLDocumentation
  - python-dotenv does not override already-set environment variables by default (`load_dotenv(override=False)`); env wins over `.env`. Source: https://saurabh-kumar.com/python-dotenv/#getting-started
- **Last reviewed:** 2026-06-06

### LLM transport — openai SDK (AsyncOpenAI) against OpenAI-compatible endpoints

- **Role in this project:** One adapter (`code_scalpel/llm/adapter.py`) talks chat-completions + streaming + native function-calling to any OpenAI-compatible `/v1` endpoint (LM Studio default `http://localhost:1234/v1`; also llama.cpp, OpenRouter, vLLM, Ollama).
- **Canonical docs:** https://github.com/openai/openai-python
- **Spec / reference:** https://platform.openai.com/docs/api-reference/chat (chat completions + tools). LM Studio compat layer: https://lmstudio.ai/docs/developer/openai-compat
- **Required validators:** none automated; the live-endpoint contract is exercised by `@pytest.mark.llm` tests under `pytest --run-llm` (hits real LM Studio) — see pipeline note.
- **Idioms and constraints:**
  - Point the client at a local server via `AsyncOpenAI(base_url="http://localhost:1234/v1", api_key=...)`. Source: https://github.com/openai/openai-python `confidence: doc-cited (unverified)`
  - **`api_key` is required by the SDK even for keyless local servers** — it reads `OPENAI_API_KEY` and raises if unset and not passed. Pass a placeholder (e.g. `"lm-studio"`/`"sk-noauth"`) for local endpoints that don't validate. Source: https://github.com/openai/openai-python `confidence: doc-cited (unverified)`
  - **Streaming tool calls arrive fragmented** in `chunk.choices[0].delta.tool_calls`; name and arguments come piecemeal and **must be accumulated** by `index` across chunks before parsing the JSON arguments. Source: https://lmstudio.ai/docs/developer/openai-compat/tools `confidence: doc-cited (unverified)`
  - Tools follow OpenAI's function-calling schema: `tools=[{"type":"function","function":{...JSON Schema...}}]`. After tool execution, append the tool result to the message history and continue the loop. Source: https://lmstudio.ai/docs/developer/openai-compat/tools `confidence: doc-cited (unverified)`
  - Context window auto-detect via `GET /v1/models` (`context_length` field); LM Studio additionally exposes loaded context via its native API. Fall back to `profiles.*.context_tokens` when absent. Source: `docs/architecture.md` "LLM endpoint contract" + https://lmstudio.ai/docs/developer/openai-compat `confidence: doc-cited (unverified)`
- **Known gotchas:**
  - **Native tool-call support is model-dependent.** LM Studio documents native tool support for Qwen, Llama-3.1/3.2, Mistral; other models use a default/best-effort format. Small or untrained models can emit malformed tool calls that LM Studio cannot parse into `tool_calls` — design for missing/garbled tool calls (matches the project's "weak model" premise). Source: https://lmstudio.ai/docs/developer/openai-compat/tools `confidence: doc-cited (unverified)`
  - LM Studio recommends its **native** `/api/v1` (or the `lmstudio` Python SDK, a declared dep) for richer stats (tokens/sec, TTFT) and model load/unload/swap; the OpenAI-compatible `/v1` layer is the portability path but does not expose those. Project uses both deliberately. Source: https://lmstudio.ai/docs/developer/rest `confidence: doc-cited (unverified)`
  - `GET /v1/models` field set is not strictly specified by the compat docs — `context_length` presence varies by backend (vLLM/llama.cpp/Ollama may differ from LM Studio); the `context_tokens` fallback is load-bearing. Source: https://lmstudio.ai/docs/developer/openai-compat (open question — see Open questions).
- **Last reviewed:** 2026-06-06

### lmstudio (LM Studio Python SDK — native surface)

- **Role in this project:** Native LM Studio operations the OpenAI compat layer can't do: model load/unload/swap on single-GPU hosts (upstream model-swap) and native streaming events (`code_scalpel/llm/lmstudio_native.py`, `lmstudio_swap.py`, `lmstudio_status.py`).
- **Canonical docs:** https://lmstudio.ai/docs/python
- **Spec / reference:** https://lmstudio.ai/docs/developer/rest/endpoints (native REST `/api/v1`)
- **Idioms and constraints:**
  - Native model management (`.model()`, load/unload) is LM-Studio-specific and **only works against an LM Studio host** — guard it behind backend detection; other OpenAI-compatible backends do not implement it. Source: https://lmstudio.ai/docs/python `confidence: doc-cited (unverified)`
- **Known gotchas:**
  - The native API surface is versioned independently of the OpenAI compat layer (see LM Studio API changelog) — pin behaviour to `lmstudio>=1.5` and re-check on LM Studio upgrades. Source: https://lmstudio.ai/docs/developer/api-changelog
- **Last reviewed:** 2026-06-06

### tree-sitter (+ tree-sitter-python) / `ast` fallback

- **Role in this project:** Granular symbol index (`code_scalpel/index/`). `tree-sitter-python` is the only declared grammar pack; stdlib `ast` is the fallback where a pack is broken/absent.
- **Canonical docs:** https://tree-sitter.github.io/tree-sitter/
- **Spec / reference:** https://github.com/tree-sitter/py-tree-sitter
- **Idioms and constraints (py-tree-sitter `~=0.25`):**
  - Construct with the modern API: `Language(tree_sitter_python.language())` then `Parser(PY_LANGUAGE)` (or `parser.language = PY_LANGUAGE`). The old `parser.set_language(...)` pattern is gone. Source: https://github.com/tree-sitter/py-tree-sitter `confidence: doc-cited (unverified)`
  - Grammar-pack and core `tree-sitter` ABI versions must be compatible — `tree-sitter~=0.25` pins both core and `tree-sitter-python~=0.25`; mismatched packs raise at `Language(...)` construction. Source: https://github.com/tree-sitter/py-tree-sitter `confidence: doc-cited (unverified)`
  - Parse `bytes`, not `str` (`parser.parse(source.encode())`); node byte offsets index the original bytes. Source: https://github.com/tree-sitter/py-tree-sitter
- **Known gotchas:**
  - Non-Python grammar packs (JS/Go/Rust) are **not declared dependencies** — any multi-language index path must degrade to `ast` (Python only) or be a no-op until the pack is added. Source: `pyproject.toml` lines 23-24.
- **Last reviewed:** 2026-06-06

### Patch engine — custom SEARCH/REPLACE (`patch/edit_block.py`) + unidiff (parse only)

- **Role in this project:** Primary code-edit path. Weak models mis-count unified-diff `@@` hunk headers, so the project applies aider-style SEARCH/REPLACE blocks, NOT unified diffs. `unidiff>=0.7` parses diffs (display/inspection), it does not apply them.
- **Canonical docs:** https://github.com/matiasb/python-unidiff (unidiff); SEARCH/REPLACE format is project-owned (`docs/architecture.md` "SEARCH/REPLACE then tool-call write_file").
- **Spec / reference:** Aider's SEARCH/REPLACE block convention as prior art: https://aider.chat/docs/unified-diffs.html and https://aider.chat/docs/more/edit-formats.html
- **Idioms and constraints:**
  - **Do not apply unified diffs.** The SEARCH block must match existing file bytes exactly (whitespace-sensitive); v0.7 superseded raw SEARCH/REPLACE with a tool-call `write_file` (`overwrite`/`replace_lines`/`insert_after_line`) for stability. Source: `docs/architecture.md` "SEARCH/REPLACE then tool-call write_file" `confidence: doc-cited (unverified)`
  - `unidiff` is parse-only here; do not reach for `unidiff` to mutate files. Source: `docs/architecture.md` "Diff / patch" row.
- **Known gotchas:**
  - Whitespace/tab drift in SEARCH blocks is the documented failure mode for qwen-14b — exact-match apply is intentionally strict; do not "fuzzy match" silently. Source: `docs/architecture.md` decision "SEARCH/REPLACE then tool-call write_file".
- **Last reviewed:** 2026-06-06

### httpx (URL / web fetch)

- **Role in this project:** Fetch URLs for `/learn --url` and web search (`code_scalpel/fetch.py`); transitive openai-SDK dep already present.
- **Canonical docs:** https://www.python-httpx.org/
- **Spec / reference:** https://www.python-httpx.org/async/
- **Idioms and constraints:**
  - Use `AsyncClient` as a context manager (`async with httpx.AsyncClient() as client:`) and **reuse one client** — do not instantiate a client inside a hot loop. Source: https://www.python-httpx.org/async/ `confidence: doc-cited (unverified)`
  - **httpx does NOT follow redirects by default** (`follow_redirects=False`) — unlike `requests`. Set `follow_redirects=True` explicitly when fetching user URLs that may 301/302. Source: https://www.python-httpx.org/compatibility/ `confidence: doc-cited (unverified)`
  - **Default timeout is 5 seconds** for all operations — set an explicit `timeout=` for slow fetches. Source: https://www.python-httpx.org/advanced/timeouts/ `confidence: doc-cited (unverified)`
  - With manual streaming (`client.send(req, stream=True)`) you must call `Response.aclose()`; prefer `async with client.stream(...)` for auto-close. Source: https://www.python-httpx.org/async/
- **Known gotchas:**
  - `follow_redirects=True` drops the `Authorization`/Bearer header on cross-origin redirect (security feature) — do not rely on auth surviving a redirect. Source: https://github.com/encode/httpx/discussions/3291
- **Last reviewed:** 2026-06-06

### sqlite3 + FTS5 (project memory store) — stdlib

- **Role in this project:** Project notes with BM25 search (`code_scalpel/memory.py`, `memory.db`); `/remember`, `/recall`, auto-recall. Zero new deps (mem0ai spike rejected).
- **Canonical docs:** https://docs.python.org/3/library/sqlite3.html
- **Spec / reference:** https://www.sqlite.org/fts5.html
- **Idioms and constraints:**
  - Create the index as `CREATE VIRTUAL TABLE ... USING fts5(...)`; FTS5 tables cannot declare column types/constraints/PRIMARY KEY and carry an implicit `rowid`. Source: https://www.sqlite.org/fts5.html `confidence: doc-cited (unverified)`
  - Rank with `ORDER BY rank` or `bm25(table[, col_weights...])`; **lower bm25() is a better match**. Source: https://www.sqlite.org/fts5.html `confidence: doc-cited (unverified)`
  - **FTS5 is not guaranteed compiled into Python's bundled sqlite3** — probe at startup (`CREATE VIRTUAL TABLE ... USING fts5` in a try/except `OperationalError`) and degrade gracefully if absent. Source: https://www.sqlite.org/fts5.html `confidence: doc-cited (unverified)`
- **Known gotchas:**
  - **User text passed raw into a `MATCH` query is FTS5 query syntax, not a literal** — special chars (`.`, `-`, `*`, `"`, parens, `AND`/`OR`/`NOT`) cause `SQLITE_ERROR: fts5: syntax error` or change meaning. Quote/escape user terms (wrap in double-quotes, double internal quotes) before MATCH. Source: https://www.sqlite.org/fts5.html `confidence: doc-cited (unverified)`
  - Always parameterize the value, but note the FTS5 *query grammar* still applies inside the bound string — parameterization prevents SQL injection, not FTS5 syntax errors. Source: https://www.sqlite.org/fts5.html
- **Last reviewed:** 2026-06-06

### pathspec (.gitignore-aware listing)

- **Role in this project:** File walking honours `.gitignore` semantics.
- **Canonical docs:** https://python-path-specification.readthedocs.io/
- **Spec / reference:** https://python-path-specification.readthedocs.io/en/latest/readme.html
- **Idioms and constraints:**
  - Build with `PathSpec.from_lines('gitignore', lines)` and test with `spec.match_file(path)`. A pattern targeting only a directory must end with `/`. Source: https://python-path-specification.readthedocs.io/en/latest/readme.html `confidence: doc-cited (unverified)`
  - For git-faithful behaviour around re-including files from excluded directories, use **`GitIgnoreSpec`**, not plain `PathSpec` — `PathSpec` follows the documented gitignore patterns, which diverge from git's actual behaviour at that edge. Source: https://python-path-specification.readthedocs.io/en/latest/readme.html `confidence: doc-cited (unverified)`
- **Known gotchas:**
  - Negation (`!pattern`) ordering matters and follows gitignore rules — a later negation can re-include; feed patterns in file order. Source: https://python-path-specification.readthedocs.io/en/latest/readme.html
- **Last reviewed:** 2026-06-06

### subprocess → git / ripgrep (with pure-Python grep fallback)

- **Role in this project:** Async ShellRunner shells out to `git` and `rg` (ripgrep); a pure-Python grep covers hosts without `rg`.
- **Canonical docs:** https://docs.python.org/3/library/asyncio-subprocess.html ; ripgrep: https://github.com/BurntSushi/ripgrep/blob/master/GUIDE.md
- **Idioms and constraints:**
  - Subprocess cwd is **pinned to the project root**; `policy.py` hard-blocks `cd`/`pushd`/redirect/`cp`/`mv` that would write outside it (SC2). Never construct a command that escapes root. Source: `docs/architecture.md` SC2.
  - Use `asyncio.create_subprocess_exec` (argv list, no shell) over `create_subprocess_shell` to avoid shell-injection; the project's hard-block regex is a defence layer, not a substitute for argv-form. Source: https://docs.python.org/3/library/asyncio-subprocess.html#security-considerations `confidence: doc-cited (unverified)`
  - `rg` may be absent — detect on PATH and fall back to the pure-Python grep; do not assume ripgrep exists. Source: `docs/architecture.md` "Git / ripgrep" row.
- **Known gotchas:**
  - `rg` honours `.gitignore` by default; a search expected to see ignored/untracked files needs `--no-ignore`/`-uu` — behaviour differs from a naive recursive walk. Source: https://github.com/BurntSushi/ripgrep/blob/master/GUIDE.md
- **Last reviewed:** 2026-06-06

### bubblewrap (`bwrap`) — shell sandbox (Linux only)

- **Role in this project:** Optional kernel-level isolation for model-issued `shell_exec`/`run_python` when `sandbox: auto|on` (`code_scalpel/tools/sandbox.py`). SC3: project RW, `/usr`/`/lib`/`/etc` RO, `/home`+`/tmp` tmpfs, network shared.
- **Canonical docs:** https://github.com/containers/bubblewrap
- **Spec / reference:** https://manpages.debian.org/unstable/bubblewrap/bwrap.1.en.html
- **Required validators:** runtime self-test — attempt a trivial `bwrap --ro-bind / / true` (or equivalent) and fall back to no-sandbox / refuse per policy if it fails. (No build-time validator; this is an availability probe.)
- **Idioms and constraints:**
  - Sandbox composition is entirely caller-defined: `--ro-bind` (read-only mount), `--bind` (read-write), `--tmpfs`, `--dev`, `--proc`, `--unshare-*` / `--share-net`, `--die-with-parent`. You must explicitly mount `/proc`, `/dev`, and needed lib symlinks — an under-specified sandbox has a broken filesystem. Source: https://github.com/containers/bubblewrap `confidence: doc-cited (unverified)`
  - "Everything mounted into the sandbox can be used to escalate privileges" — keep the writable surface minimal (project RW only) per SC3. Source: https://github.com/containers/bubblewrap `confidence: doc-cited (unverified)`
  - **bwrap requires unprivileged user namespaces.** It is the security boundary for SC3 — a load-bearing idiom. Source: https://github.com/containers/bubblewrap `confidence: doc-cited (unverified)`
- **Known gotchas:**
  - **Ubuntu 23.10+/24.04 sets `kernel.apparmor_restrict_unprivileged_userns=1` by default**, so `bwrap` fails with `bwrap: ... Operation not permitted` / "No permissions to creating new namespace" out of the box. Fix is an AppArmor profile for `/usr/bin/bwrap` (`userns` flag) or, on plain Debian, `sysctl kernel.unprivileged_userns_clone=1`. The project must **detect this failure and degrade** (fall back to policy-only / refuse), not crash. Source: https://github.com/containers/bubblewrap/issues/324 ; https://www.jdhodges.com/blog/codex-sandbox-ubuntu-24-04-fix/ `confidence: doc-cited (unverified)`
  - bwrap is Linux-only — no macOS/Windows sandbox path; on those hosts `sandbox` must be off / policy-only. Source: https://github.com/containers/bubblewrap
- **Last reviewed:** 2026-06-06

### @mermaid-js/mermaid-cli (`mmdc`) + rich-pixels — optional `[diagrams]` extra

- **Role in this project:** Render ```mermaid``` blocks from model replies inside the TUI. `mmdc` (npm, on PATH) produces a PNG; `rich-pixels` draws it as Unicode half-blocks. Without both, fall back to raw text of the block.
- **Canonical docs:** https://github.com/mermaid-js/mermaid-cli ; https://github.com/darrenburns/rich-pixels
- **Idioms and constraints:**
  - `mmdc` is an **npm-installed external binary** (`npm i -g @mermaid-js/mermaid-cli`), not a pip dep — detect on PATH and fall back to raw text when absent. Source: `pyproject.toml` lines 41-48; `docs/architecture.md` "Integration contract". `confidence: doc-cited (unverified)`
  - `[diagrams]` (`rich-pixels`) is the Python half; the npm `mmdc` is a separate manual install — both required for image render. Source: `pyproject.toml` lines 46-48.
- **Known gotchas:**
  - `mmdc` uses headless Chromium (Puppeteer) under the hood; in restricted/CI/sandboxed environments it may need `--no-sandbox` Puppeteer args and can be slow — treat render as best-effort, never block the turn on it. Source: https://github.com/mermaid-js/mermaid-cli
- **Last reviewed:** 2026-06-06

### Dev/build toolchain — ruff, mypy --strict, pytest(+asyncio/cov), hatchling

- **Role in this project:** Pre-commit gates (lint+format, types, tests) and the `pyproject.toml`-only build (`hatchling`).
- **Canonical docs:** ruff https://docs.astral.sh/ruff/ · mypy https://mypy.readthedocs.io/ · pytest https://docs.pytest.org/ · pytest-asyncio https://pytest-asyncio.readthedocs.io/ · hatchling https://hatch.pypa.io/latest/
- **Required validators:** see the pipeline table below — `ruff check .`, `ruff format --check .`, `mypy code_scalpel/`, `pytest`.
- **Idioms and constraints:**
  - **All config lives in `pyproject.toml`** — no separate `.ruff.toml`/`mypy.ini`/`pytest.ini`. Tune the relevant section in `pyproject.toml`. Source: `DEVELOPING.md` "Стек"; `pyproject.toml`. `confidence: doc-cited (unverified)`
  - ruff is formatter (`ruff format`, replaces black) **and** linter (`ruff check`); current `lint.select = ["E","F","I","UP","B","SIM"]`, `ignore = ["E501"]`, `line-length = 100`, double quotes. Source: `pyproject.toml` lines 57-75. `confidence: doc-cited (unverified)`
  - **`mypy --strict`** (`[tool.mypy] strict = true`), checked over `code_scalpel/`; all public functions/methods must be type-annotated — a merge blocker. Source: `pyproject.toml` lines 77-84; `docs/architecture.md`. `confidence: doc-cited (unverified)`
  - pytest runs with `asyncio_mode = "auto"` (no `@pytest.mark.asyncio` needed), `testpaths = ["tests"]`. The `llm` marker hits a live LM Studio and runs **only** with `pytest --run-llm`. Source: `pyproject.toml` lines 86-91. `confidence: doc-cited (unverified)`
  - ruff/mypy **exclude** `scripts/probes_v2/fixtures` and `docs/article/probe-runs` (intentional "foreign project" fixtures). Do not lint those paths. Source: `pyproject.toml` lines 65-68, 81-84.
- **Known gotchas:**
  - `mypy --strict` over `code_scalpel/` only — `tests/` are not strict-checked by the project's command; do not assume tests are type-gated. Source: `DEVELOPING.md` "Перед коммитом" (`mypy code_scalpel/`).
  - `ignore_missing_imports = true` is set — missing stubs for third-party libs won't fail mypy; do not rely on mypy to catch a wrong third-party import path. Source: `pyproject.toml` line 80.
- **Last reviewed:** 2026-06-06

---

## Validators wired into pipeline

Every validator listed here must be in the project's `Pipeline` block in `CLAUDE.md`. Pipeline runs them as mandatory gates — green pipeline means every listed validator passed.

| Validator | Command | Gates |
|---|---|---|
| ruff lint | `ruff check .` | Lint errors (E/F/I/UP/B/SIM); `E501` ignored. Import sort + bugbear + simplify. |
| ruff format check | `ruff format --check .` | Formatting drift (double-quote, line-length 100). |
| mypy strict | `mypy code_scalpel/` | Full static type check over the package; all public defs annotated. |
| pytest | `pytest` | Unit + integration tests (mocks for LLM/shell). `pytest -x` for stop-on-first-fail locally. |
| pytest (live-LLM, opt-in) | `pytest --run-llm` | `@pytest.mark.llm` tests against a real LM Studio endpoint — **not** a default gate (slow, non-deterministic, needs LM Studio running). |

> Note: `--cov` (`pytest --cov --cov-report=term-missing`) is available via `pytest-cov` (`[tool.coverage.run] source = ["code_scalpel"]`) but no coverage **floor** is wired as a gate today.

---

## Integration contracts

For each external system the project integrates with — what local artifact carries the contract, how it gets delivered, and which tool validates it end-to-end.

| External system | Local artifact in repo | Delivery mechanism | Validator |
|---|---|---|---|
| OpenAI-compatible LLM endpoint (LM Studio / llama.cpp / OpenRouter / vLLM / Ollama) | `code_scalpel/llm/adapter.py` (chat/stream/tools client) + `profiles.*` in config (`base_url`, `context_tokens`) | Runtime HTTP to `<base_url>/v1`; API key from env (`OPENAI_API_KEY`/`OPENROUTER_API_KEY`/`LMSTUDIO_API_KEY`), placeholder allowed for keyless local | `pytest --run-llm` (live `@pytest.mark.llm` tests) + `GET /v1/models` context probe at startup |
| LM Studio native surface | `code_scalpel/llm/lmstudio_native.py`, `lmstudio_swap.py`, `lmstudio_status.py` (via `lmstudio` SDK) | Runtime calls to LM Studio native `/api/v1` on `localhost:1234` | Backend-detection guard + live LM Studio under `--run-llm` |
| bubblewrap sandbox (`bwrap`) | `code_scalpel/tools/sandbox.py` (argv builder: `--ro-bind`/`--bind`/`--tmpfs`/`--dev`/`--proc`) | External `bwrap` binary on PATH (Linux); invoked per `shell_exec`/`run_python` when `sandbox: auto|on` | Runtime availability probe (trivial `bwrap` exec); degrade to policy-only on failure (userns/AppArmor) |
| git | `subprocess` argv via async ShellRunner | External `git` on PATH; cwd pinned to project root | Per-task git-HEAD advance check in `run_plan` |
| ripgrep (`rg`) | `code_scalpel/tools/search.py` (argv); pure-Python grep fallback | External `rg` on PATH (optional) | PATH detection → pure-Python fallback |
| @mermaid-js/mermaid-cli (`mmdc`) | `code_scalpel/diagrams.py` / `mermaid/` | External npm binary on PATH (optional `[diagrams]`) | PATH detection → raw-text fallback |
| Python package install | `pyproject.toml` (hatchling) | `pip install -e ".[dev]"` (+ optional `[diagrams]`/`[build]`); `.deb`/PyInstaller binary for release | `code-scalpel --version` (importlib.metadata resolves) + build via hatchling/pyinstaller |

---

## AI-specific minimums → ruff-rule mapping

The project declares AI-specific minimums as conventions in `docs/architecture.md` `### AI-specific minimums` (the numbers live **only** there — this mapping says *which rule carries each*, never restates the number). For Python + ruff, each minimum maps to the concrete ruff rule that *would* encode it. **Critical reality:** the current `lint.select = ["E","F","I","UP","B","SIM"]` enables **none** of the rules below — every minimum is currently **AI-self-policed**, not linter-enforced.

| AI-minimum (home: `### AI-specific minimums`) | Carrying ruff rule | Enforcement encoding (config) | Enabled today? | Status |
|---|---|---|---|---|
| max function/method length (statements) | `PLR0915` too-many-statements | `[tool.ruff.lint.pylint] max-statements = N` | No (`PLR` not in select) | convention / AI-self-policed |
| cyclomatic-complexity cap | `C901` complex-structure (mccabe) | `[tool.ruff.lint.mccabe] max-complexity = N` | No (`C90` not in select) | convention / AI-self-policed |
| max function arguments | `PLR0913` too-many-arguments | `[tool.ruff.lint.pylint] max-args = N` | No | convention / AI-self-policed |
| max branches (proxy for nesting/complexity) | `PLR0912` too-many-branches | `[tool.ruff.lint.pylint] max-branches = N` | No | convention / AI-self-policed |
| max return statements (proxy) | `PLR0911` too-many-return-statements | `[tool.ruff.lint.pylint] max-returns = N` | No | convention / AI-self-policed |
| max locals (proxy) | `PLR0914` too-many-locals | `[tool.ruff.lint.pylint] max-locals = N` | No | convention / AI-self-policed |
| **max source file length** | **none — ruff has no max-lines-per-file rule** | n/a (ruff cannot express it) | n/a | **convention-only; AI-review backstopped** |
| no file-level lint suppressions | partial — ruff flags unused `# noqa` (`RUF100`) but cannot forbid `# ruff: noqa` file directives | `RUF100` (catches stale noqa only) | No (`RUF` not in select) | convention / AI-self-policed |
| new-code coverage floor | none — coverage floor is a `pytest-cov`/`coverage` gate, not a ruff rule | `[tool.coverage.report] fail_under = N` (coverage, not ruff) | No floor wired | convention / AI-self-policed |
| no duplicate / copy-paste code | **none — ruff has no copy-paste detector** | n/a (ruff cannot express it) | n/a | **convention-only; covered by the `smell / hygiene` review type (`### Review typology` in `workflow/review-typology.md`), which names duplication and cross-module concerns as AI-evaluated smells** |

**Rules that ruff cannot express at all** (so they stay AI-review-backstopped regardless of config): **max-lines-per-file**, **copy-paste/duplication detection**, and **cross-module duplication** — these fall to the `smell / hygiene` review type's AI half per `### Review typology` in `workflow/review-typology.md`. `RUF100`/`# ruff: noqa` file-suppression forbidding is only partial in ruff.

**Migration hazard (do not silently enable).** Turning the `PLR*`/`C901` families on now would **fail lint on legacy files** — `agent.py` (~3289 LOC, far past any sane `max-statements`), `tui/app.py` (~2129 LOC), `tools/agent_tools.py`, `fork.py` all exceed the stated minimums. A clean enable path, if the maintainer chooses to enforce, is gradual:
- add the families to `lint.select` **plus** `[tool.ruff.lint.per-file-ignores]` carving out the known-oversized modules (e.g. `"code_scalpel/agent.py" = ["PLR0915","PLR0912","C901"]`), then shrink the ignore list as modules are refactored; **or**
- enforce on **new/changed code only** (the protocol's new-code-gating cadence), leaving legacy untouched.
This document **maps and flags** the option; it does **not** prescribe enabling it.

---

## How to extend this document

Only `pm-stack-researcher` edits this file. Other agents read it. If `pm-coder` or `pm-plan-checker` notices a missing rule or stale entry, they surface it to the orchestrator — orchestrator spawns `pm-stack-researcher` to update.

Each rule must cite a source URL. Unsourced claims do not belong here.
