# code-scalpel

A TUI coding agent that works with your code through local or cloud LLMs.
Small context. Precise patches. You stay in control.

```
cd your-project
code-scalpel
```

---

## What you can do

**Ask questions about the codebase**
"Where is the auth logic?", "Is this function used anywhere?", "Walk me through this flow." The agent navigates the project, reads relevant files, and answers — without you having to specify which files to look at.

**Fix a bug or add a feature**
Describe the task in plain text. The agent proposes a diff, you review it, confirm, and it applies the patch and runs your tests. If tests fail, it retries. If it can't fix it, it rolls back.

**Plan a larger task**
The agent breaks your request into concrete steps (T001, T002 …). You can then execute them one by one or let it run through them autonomously.

**Run shell commands — with confirmation**
The agent can propose and execute shell commands. In the default skeptic mode you see the command and approve or reject it before it runs. Destructive commands (`rm -rf`, `sudo`, `mkfs`, …) are hard-blocked — you can't approve them by accident.

**Teach it about your tools**
Use `/learn <url>` to fetch docs or paste text — the agent writes a recipe file. On future turns that recipe is injected into context automatically: always (eager recipes) or only when your task mentions that tool by name (lazy recipes). No more explaining your stack from scratch every session.

---

## Install

Requires Python 3.11+ and an OpenAI-compatible LLM server.

```bash
pip install code-scalpel
```

Or from source:

```bash
git clone https://github.com/aadegtyarev/code-scalpel
cd code-scalpel
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

### LLM backend

The default setup expects [LM Studio](https://lmstudio.ai) running on `localhost:1234`.
Load a model (tested on `qwen2.5-coder-14b-instruct`), start the local server, done.

Any OpenAI-compatible server works — llama.cpp, vLLM, Ollama, OpenRouter:

```bash
# llama.cpp example
llama-server --model qwen2.5-coder-14b-Q4_K_M.gguf --port 1234 -ngl 99
```

---

## Quick start

```bash
cd your-project
code-scalpel          # opens TUI in current directory
```

The footer shows the active mode and model name. Switch modes with `Ctrl+T`.

Type a task and press Enter. The agent reads your project, calls tools, and streams the response inline. After each reply a summary line shows how many tools were called, tokens used, and context fill:

```
⤷ 🔧 3 tools · ↓ 312 tokens · 4.1s · ctx 2k/16k (12%)
```

---

## Modes

Switch with `Ctrl+T` or `/mode <name>`.

| Mode | What it does |
|---|---|
| `ask` | Questions, exploration, code review. Never modifies files. |
| `plan` | Breaks a task into numbered steps. |
| `code` | Proposes a patch. You review and confirm before it applies. |
| `run` | Executes plan steps one by one with confirmation at each step. |

---

## Commands

| Command | What it does |
|---|---|
| `/learn <url>` | Fetch a page and save it as a recipe. |
| `/learn` | Open editor to write a recipe manually. |
| `/remember <fact>` | Save a note to project memory (sqlite, persists across sessions). |
| `/recall [query]` | Show saved notes; with a query, searches by full-text. |
| `/compact` | Summarise conversation history to free up context. |
| `/map` | Show the full project file tree. |
| `/tasks` | Show the current plan from `.code-scalpel/TASKS.md`. |
| `/stats` | Session summary: tokens, cost, timing. |
| `/new` | Clear session and start fresh. |
| `/mode <name>` | Switch mode. |

---

## Keyboard shortcuts

| Key | Action |
|---|---|
| `Ctrl+T` | Cycle through modes |
| `Ctrl+O` | Open last tool result in a full-screen popup |
| `Ctrl+↑` / `Ctrl+↓` | Jump between tool cards in history |
| `↑` / `↓` | Input history (like a shell) |
| `Esc` | Cancel streaming response |
| `Ctrl+Q` | Quit |

---

## Recipes (`/learn`)

Recipes let the agent remember things that aren't in your code — how your team uses a particular tool, a library's quirks, conventions that live only in someone's head.

```bash
/learn https://redis.io/docs/manual/data-types/
# agent fetches, summarises, writes .code-scalpel/recipes/redis.md
```

Two loading modes, set in the recipe's frontmatter:

- **eager** — injected on every turn. Use for things that are always relevant: "we test with pytest -x", "all Python must be typed".
- **lazy** — injected only when your task mentions a keyword. Use for tool-specific knowledge: the redis recipe loads when you ask about caching, not when you're fixing a CI script.

Three recipe locations, in priority order (project overrides user overrides built-in):

1. `.code-scalpel/recipes/` — project-local
2. `~/.config/code-scalpel/recipes/` — yours across all projects
3. Built-in recipes that ship with the agent

---

## Configuration

No config file needed to get started. To customise:

```yaml
# ~/.config/code-scalpel/config.yaml   (applies to all projects)
# .code-scalpel/config.yaml            (this project only)

profiles:
  local:
    provider: lmstudio
    model: auto          # auto-detects the loaded model; or set explicitly
    temperature:
      ask: 0.1
      code: 0.2
      debug: 0.5

agent:
  trust: skeptic         # skeptic | optimist | yolo
  max_file_lines: 400
  max_debug_attempts: 2
```

`trust` controls how much the agent can do without asking:

| Level | Shell commands | Patch apply |
|---|---|---|
| `skeptic` (default) | Confirmation required | Confirmation required |
| `optimist` | Runs after hard-block check | Auto-applied |
| `yolo` | No filters | Auto-applied |

To use a cloud provider or a different local server:

```yaml
profiles:
  openrouter:
    provider: openrouter
    model: qwen/qwen-2.5-coder-32b-instruct
  llamacpp:
    provider: lmstudio     # same OpenAI-compatible adapter
    base_url: http://localhost:8080
    model: auto
```

API keys go in `.env` (never in yaml):

```bash
OPENROUTER_API_KEY=sk-or-...
```

---

## Contributing

See [DEVELOPING.md](DEVELOPING.md) — stack, commands, branch and release conventions.

## License

AGPL-3.0-or-later
