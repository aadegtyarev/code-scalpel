# code-scalpel — what it is and why

Authored product front door.

## Why this exists

You want to work on your own code with an AI assistant, but on a model that
runs **on your own machine** — private, no cloud, no per-token bill. The
catch with weak local models is that they fall apart on big context and big
changes: feed a 14B model a whole repo and a sweeping diff and it loses the
thread, invents methods, and breaks the build.

code-scalpel is built to get reliable work out of exactly those weak local
models — and to do it with **controlled autonomy**. Instead of one giant
prompt, it keeps everything small: a small slice of context, a small
verifiable patch, a fast test. That smallness is what makes autonomy safe,
so the model can actually *drive* the work itself within trust levels you
set and turn up or down at any moment:

- **skeptic** — you approve every shell command and every code change before
  it happens (the default);
- **optimist** — the agent applies changes on its own, but pauses with a
  timed prompt at real decision points;
- **yolo** — full autonomy, for a throwaway VM or container.

When the model hits a genuinely hard call (which library? which approach?),
it doesn't guess blindly — it **delegates**: to you, to itself acting as an
architect, or to a stronger "upstream" model that resolves a batch of hard
decisions at once. You stay in control of how much it does without asking,
in one place.

It is for a **solo developer working on their own repository**, who would
rather run a private local model than send their code to the cloud.

## What it does today

A terminal (TUI) coding agent with a handful of modes you switch between,
all driven through one local LLM:

- **Ask** — ask questions about your codebase in plain language and get
  grounded answers (it cites real `path:symbol`, doesn't invent methods)
  without touching any files.
- **Code** — hand it one small task; it reads only what it needs, proposes
  a single change shown as a diff, and once applied runs your tests. Small,
  inspectable, reversible.
- **Plan** — turn a bigger goal into an ordered, editable task list, with
  the skills each task needs annotated and architectural decision points
  surfaced up front, before any code is written.
- **Run the plan (`/go`)** — let the agent work through the task list on its
  own — read → write → test → commit per task — with stop conditions, an
  auto-commit safety net, and a run summary of what was done, committed, and
  what still needs you.
- **Review** — point it at a file or a diff and get a structured critique
  (summary, tagged issues with line numbers, suggestions) without it
  changing anything.
- **Debug** — when something breaks, it investigates hypothesis-first
  (running small snippets to check ideas) and proposes a fix instead of
  blindly patching.
- **Memory & learning** — `/remember` a project fact and it is auto-recalled
  later; `/learn` a tool's conventions from the model's knowledge or a docs
  URL and it becomes a reusable recipe. It stops re-asking what you already
  told it.
- **Setup & trust** — `code-scalpel init` gets you from install to a working
  agent in one guided step; one live trust knob (skeptic / optimist / yolo)
  governs shell confirmation, patch auto-apply, and decision delegation
  together.

**Not yet supported / current boundaries:**

- **Linux only** — the kernel-level sandbox (`bwrap`) is Linux-only;
  Windows/macOS have no sandboxed shell path.
- **Full symbol index is Python-only** — other languages fall back to a
  coarser parse, not the full tree-sitter symbol index.
- **Memory search is keyword/BM25 only** — no semantic/vector retrieval, no
  contradiction-detection across notes.
- **Code edits are SEARCH/REPLACE / `write_file` based**, not unified diffs
  (weak models can't reliably produce those).
- **You run the LLM server yourself** — code-scalpel talks to LM Studio (or
  any OpenAI-compatible endpoint); it doesn't manage the model server.

## How people find it

code-scalpel is distributed in the open. The main way to get it is the
**GitHub Releases** page — a Linux `.deb` package and a standalone binary —
with the source itself in the **GitHub repository**. **PyPI** (`pip install
code-scalpel`) is planned but not yet published. The main way people hear
about it is the **technical article** being written alongside the tool,
which walks through how the system was designed — that write-up is the
primary discovery channel that brings people to the repo.

## Out of scope (for now)

- **Not a replacement for cloud frontier agents** (Claude Code and the
  like). The goal is to extract the most from a weak *local* model — not to
  compete with frontier models on their own turf.
- **Single-user, own-repo** — it is a personal tool for one developer on one
  repository, not a multi-user or hosted service.
- **Linux-only for now** — the `bwrap` sandbox dependency means Windows and
  macOS are out of scope.
- **Full symbol-index support is Python-only for now** — other languages go
  through an `ast` fallback, not the full tree-sitter index.

> **Controlled autonomy is explicitly *in* scope** — it is a direction of
> development, not a limitation. The trust levels (skeptic / optimist /
> yolo) and the delegation of hard decisions are core to the product, not
> something deferred.

## Documents

- [Architecture](architecture.md) — stack, decisions, constraints
- [User journeys](user-journeys.md) — how the product is used, flow by flow
- [Threat model](threat-model.md) — shell execution, patch apply, sandbox boundary
- [UI guide](ui-guide.md) — TUI conventions

## Features

Contract → features map (what each guarantee includes, which features built it, reviews): [`docs/product-map.md`](product-map.md).
