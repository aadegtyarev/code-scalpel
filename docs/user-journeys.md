# User Journeys

> Canonical user journeys for code-scalpel.
> Derived bottom-up from CLI entry points, TUI slash commands/keybindings, agent
> modes, and `plan.md` scenarios. Format / taxonomy identifiers live once
> in `docs/architecture.md` `## Behavioral contract` and are referenced here, never restated.

The single user role is **a developer using this terminal agent on their
own codebase through a weak local LLM** (default: qwen2.5-coder-14b in LM
Studio). They want small, reviewable changes — not an autonomous
programmer.

---

## Journey 1: Developer — First-time setup of a project

**Entry context:** the developer just installed `code-scalpel` and wants
to point it at one of their repositories.

| Step | What the user does | What they expect | What can go wrong |
|---|---|---|---|
| 1. | Runs `code-scalpel init` in the project dir | A short interactive walk-through (provider, model name, sandbox) | An existing config asks to overwrite; declining aborts cleanly |
| 2. | Picks an LLM provider and model | A `.code-scalpel/config.yaml` is written with sensible defaults | They pick a provider whose key isn't set yet — config notes the env var to set |
| 3. | Confirms the sandbox choice (auto/on/off) | The config records it; a `.gitignore` entry for `.code-scalpel/` is added | `bwrap` isn't installed or the host restricts user namespaces and they chose `on` — sandbox refuses/degrades later |
| 4. | Runs `code-scalpel` to launch the TUI | The agent starts in `ask` mode, footer shows the resolved model name | The LLM endpoint is down — turns fail loudly rather than hang silently |

**Drop-off points:** confusion about which provider to pick; the API-key
env var not being set before the first real turn.

**Invariants:** the LLM endpoint must be reachable before any turn produces
output. Format / taxonomy invariants — see `docs/architecture.md`
`## Behavioral contract`.

---

## Journey 2: Developer — Ask a question about the codebase (`ask`)

**Entry context:** they want to understand the project before changing it
("where is X used?", "how should I add Y?").

| Step | What the user does | What they expect | What can go wrong |
|---|---|---|---|
| 1. | Types a question in `ask` mode | The agent answers using the project map, search, and memory — without reading whole files unless needed | The model invents a method that doesn't exist — grounding rules + read-before-show guard catch most cases |
| 2. | Asks a follow-up | The agent recalls earlier context and stored notes automatically | Context fills up; the agent offers to compact |
| 3. | Says "ok, let's build it" | The agent suggests switching to plan or code mode | — |

**Invariants:** `ask` never modifies code. Auto-recall pulls top notes
only when something matches. Mode taxonomy + grounding behaviour — see
`docs/architecture.md` `## Behavioral contract`.

---

## Journey 3: Developer — Make one small change (`code`)

**Entry context:** a concrete, small task ("fix crash when query is
empty", "add a flag to this command").

| Step | What the user does | What they expect | What can go wrong |
|---|---|---|---|
| 1. | Switches to `code` mode (Ctrl+T) and types the task | The agent reads only the files it needs, then proposes a file write shown as a diff card | It edits the wrong file / too much — the diff preview is the safety gate |
| 2. | Reviews the diff card | At skeptic trust, an explicit apply / reject / regenerate gate; at optimist/yolo it auto-applies | A model whitespace error breaks the write — `write_file` modes avoid SEARCH/REPLACE fragility |
| 3. | Confirms apply | The change lands and tests run automatically | Tests fail — the agent runs a debug pass and offers a retry with a fix hint |
| 4. | Sees the result | Pass/fail summary; on failure the partial change is kept on disk to inspect | A retry loops — anti-loop caps attempts |

**Drop-off points:** an unwanted edit applied in optimist/yolo without
review; a confusing failed-test message.

**Invariants:** at skeptic, nothing is applied without confirmation; a
failed change is kept on disk, not discarded. Trust levels and the apply
gate — see `docs/architecture.md` `## Behavioral contract`.

---

## Journey 4: Developer — Plan a multi-step task (`plan`)

**Entry context:** the task is bigger than one edit ("add search via
ripgrep, no vectors").

| Step | What the user does | What they expect | What can go wrong |
|---|---|---|---|
| 1. | Switches to `plan` and describes the goal | The agent builds a task list, asking clarifying questions | The plan is too coarse / has analytic non-tasks — verification later catches these |
| 2. | (auto) The agent annotates each task with the skills it needs | A per-task skills line, visible and editable | Wrong skill annotated — the user can edit, or `/annotate` re-runs |
| 3. | (auto, opt-in) The agent detects architectural forks in the plan | Decision points surfaced before any code | A degenerate single-option fork — the detector drops these |
| 4. | Reviews / edits the task list | A clear, ordered plan they can hand to `/go` | They edit the task file mid-run later — the runner detects the change and stops |

**Invariants:** plan mode does not execute code; the task file is the
source of truth and written atomically. Carry-over from `ask` can seed the
planner via compaction. Status / task taxonomy — see `docs/architecture.md`
`## Behavioral contract`.

---

## Journey 5: Developer — Run the plan autonomously (`/go`)

**Entry context:** a task list exists; the developer wants the agent to
work through it.

| Step | What the user does | What they expect | What can go wrong |
|---|---|---|---|
| 1. | Runs `/go` and picks a scope (next task / full plan / manual retry) | The agent ensures a git repo exists, then executes tasks one by one | No git repo — the agent auto-inits one with a starter `.gitignore` |
| 2. | Watches per-task progress cards | Each task: read → write → test → commit, with optional per-step review and test-sanity checks | A task fails repeatedly — the loop stops after N consecutive failures, keeping partial progress on disk |
| 3. | Sees, per task, whether the deliverable actually ran | A card showing the agent ran the finished deliverable the way a user would (e.g. asking it for its help text) and whether it ran cleanly. A task is **failed by this check only at the very end** — when the project is meant to be a runnable command-line tool, this is its final step, and the finished deliverable still doesn't actually run. Earlier steps (the tool isn't supposed to run yet) and projects with no runnable tool (e.g. a library) are only *observed*, never failed by it | At the final step the deliverable doesn't run at all (the classic "looked done but never executed" case) — that final task is demoted to failed instead of passing silently. An early step that is still building toward a runnable tool is shown informationally and is never failed by this check; a library or other non-CLI project is likewise only noted, never wrongly failed. At `optimist`/`yolo` trust the agent first **tries to fix it itself** — it re-feeds the failing run back to the model, rebuilds, and re-runs the deliverable up to a few bounded attempts before finally marking the task failed; at `skeptic` it fails immediately and waits for the human |
| 4. | (at a fork) Sees a choice card or auto-resolution | At skeptic a choice card waits; at optimist a timed card; at yolo it auto-resolves (critical forks still pause) | The auto-pick is wrong — recorded for later override review |
| 5. | Sees the run summary | Tasks done/failed, commits made, any pending upstream forks | The model forgot to commit — an auto-commit hook commits the task for it |
| 6. | (optional) Runs `/escalate` or lets `/go` end | Pending forks are flushed through a stronger upstream model in one batch; disagreements are surfaced as overrides | Upstream model swap fails — forks reported unresolved, no silent code rewrite |

**Drop-off points:** a stalled task that keeps failing; an auto-resolved
fork the developer disagrees with.

**Invariants:** per-task git HEAD must advance or the task is `failed`;
overrides never auto-rewrite code. The deliverable run-check (run-smoke)
**fails a task only when three things hold together**: the project is meant
to be a runnable command-line tool, the task is the plan's **final step**
(where the tool should be runnable end-to-end), and the finished deliverable
**still doesn't run**. So a `done` final step of a CLI project means the
tool really worked. At `optimist`/`yolo` trust, a failing
final-deliverable run does not fail the task on the first try — the agent
**auto-fixes**: it rebuilds and re-runs the deliverable a bounded number of
times before finally marking it failed. At `skeptic` it never auto-rebuilds
— a failing final-deliverable run fails the task immediately and waits for
the human, exactly as before. **Earlier steps are never failed by this check** (the
tool isn't supposed to run yet), and **projects with no runnable tool (e.g. a
library) are never failed by it either** — the run stays informational there.
The acceptance check may be auto-derived (one LLM pass per acceptance-less
task at `/go`) and written into the plan so it is the same on every later
run. Trust-driven fork resolution, status taxonomy, the run-smoke verdict
values, and stop reasons — see `docs/architecture.md`
`## Behavioral contract`.

---

## Journey 6: Developer — Review code or a diff (`review`)

**Entry context:** they want a structured critique of a file or a pending
change.

| Step | What the user does | What they expect | What can go wrong |
|---|---|---|---|
| 1. | Switches to `review` and points at a file or diff | The agent reads the code and returns Summary / tagged Issues with file:line / Suggestions | The model proposes a patch instead — review mode forbids SEARCH/REPLACE output |
| 2. | Reads the findings | Issues tagged by category, each with a line citation | Findings cite a wrong line — review reads the actual file first |

**Invariants:** review never modifies code and emits no patch output.
Issue tag taxonomy — see `docs/architecture.md` `## Behavioral contract`.

---

## Journey 7: Developer — Debug a failure (`/mode debug`)

**Entry context:** something is broken and they want a hypothesis-driven
investigation.

| Step | What the user does | What they expect | What can go wrong |
|---|---|---|---|
| 1. | Switches to debug mode and describes the failure | The agent forms a hypothesis, gathers evidence (can run small Python snippets to test ideas without writing files), then suggests a fix | It thrashes between hypotheses — anti-loop caps attempts |
| 2. | Applies / iterates | A compact fix hint instead of raw traceback dumps | — |

**Invariants:** the debug pass cannot write files (investigate, don't
mutate) and is bounded by attempt caps. Tool-surface and step semantics —
see `docs/architecture.md` `## Behavioral contract`.

---

## Journey 8: Developer — Teach the agent project knowledge (`/learn`, `/remember`)

**Entry context:** they want the agent to remember a fact or learn a
technology's conventions so it stops re-asking.

| Step | What the user does | What they expect | What can go wrong |
|---|---|---|---|
| 1. | Runs `/remember <fact>` | The note is stored in project memory and auto-recalled on relevant future turns | A huge note would bloat every turn — notes are size-capped |
| 2. | Runs `/recall [query]` | A list/search of stored notes | — |
| 3. | Runs `/learn <name> [--url] [--type recipe\|skill]` | The agent writes a recipe/skill markdown file (lazy-loaded by keyword by default) and shows a hint about it | A bad URL fetch fails the learn step cleanly |

**Invariants:** lazy recipes inject only when the task text matches a
keyword; project recipes beat user beats bundled. Notes and recipes persist
across sessions — `/new` wipes session+state but `memory.db` persists
separately `[?]` (confirm). Loading semantics + discovery order — see
`docs/architecture.md` `## Behavioral contract`.

---

## Journey 9: Developer — Resume an interrupted session

**Entry context:** the TUI was killed / the machine rebooted mid-task.

| Step | What the user does | What they expect | What can go wrong |
|---|---|---|---|
| 1. | Re-launches `code-scalpel` in the same dir | A notice that an unfinished session / dirty patch was found | The history was hand-edited — the resume guard detects the mismatch and starts fresh |
| 2. | Chooses continue vs restart | Continue picks up where it stopped; pending upstream forks are surfaced as "N forks waiting" | — |

**Invariants:** `STATE.json` is written atomically on each meaningful
transition; the resume hash distinguishes "same state we saved" from "user
edited / fresh start". See `docs/architecture.md` `## Behavioral contract`.

---

## Journey 10: Developer — Use external tools via MCP (`mcp.json`, `/mcp`)

**Entry context:** the developer wants the agent to call tools from an
external MCP server (e.g. a browser-automation server, or a remote
tool endpoint) alongside the built-in tools.

| Step | What the user does | What they expect | What can go wrong |
|---|---|---|---|
| 1. | Writes `.code-scalpel/mcp.json` declaring one or more servers under the standard `mcpServers` key (a `command` entry runs a local subprocess; a `url` entry connects to a remote endpoint) | Copy a server block from another client's config and it works unchanged; the legacy `servers` key is still read for back-compat | A server entry has neither `command` nor `url` (or both) — it is reported as a per-server config error, not a crash |
| 2. | Launches `code-scalpel` | On startup the declared servers connect in the background and a notice reports which connected and how many tools each loaded | A server's command isn't installed / a URL is unreachable — that server is reported failed with the reason; the others still load and the session is unaffected |
| 3. | Gives a task in any mode | The agent uses the MCP tools transparently alongside native tools; a built-in tool name always wins over a same-named MCP tool; output from an external tool enters the conversation framed as untrusted (data, not instructions — see the `## Behavioral contract` untrusted-content framing) | A tool hangs — the per-call timeout fires and the turn continues rather than deadlocking; a failed MCP call is reported to the model as a failed tool call, not silently swallowed |
| 4. | Runs `/mcp` | A per-server status list (connected / failed-with-reason) and the tools each server exposes | A server dropped after startup — its status is shown; reconnection is manual via `/mcp reload` |
| 5. | Edits `mcp.json`, then runs `/mcp reload` | The manager tears down and reconnects from the current config without restarting the TUI | A reload during an in-flight MCP call — the manager handles it without corrupting the call |

**Drop-off points:** a server that fails to connect and the reason is
unclear; confusion about which transport a given entry uses.

**Invariants:** MCP servers are launched only from user-authored config,
never from model output, and run outside the shell sandbox — see
`docs/architecture.md` `## Security surface` (SC9) and
`docs/threat-model.md`. Native tools always take precedence over MCP tools
on a name collision; MCP tool output is treated as untrusted content,
framed before it reaches the model (SC10). The config schema
(`mcpServers`/legacy `servers`, stdio vs HTTP transport selection), tool
namespacing, the per-call timeout, and the untrusted-content framing — see
`docs/architecture.md` `## Behavioral contract`.

---

## Cross-journey interactions

There is a single human role, but the agent delegates decisions to other
"brains" mid-journey:
- **Fork delegation** (Journeys 4–5): a hard architectural choice is
  routed to the human, the same local model in an architect role, or a
  stronger upstream model — selected by the trust level.
- **Narrow passes** (Journeys 3–5): per-step review, test-sanity judging,
  commit-message authoring, and debug hypotheses run as separate
  single-purpose model turns that feed the main flow.
- **Memory** (Journey 8 ↔ all): notes and recipes learned once surface
  automatically in later `ask`/`code`/`plan` turns.
