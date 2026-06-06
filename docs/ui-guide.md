# UI Guide — code-scalpel TUI

**This is the canonical UX/ergonomics contract for the code-scalpel TUI** —
the experience to preserve if the TUI is changed or rewritten. The
*implementation* is not frozen; the *experience* is. It is **rewrite-grade**:
complete and precise enough to rebuild the TUI from scratch and reproduce the
exact user experience — layout, modes, keybindings, card behaviors,
streaming, focus model, status surfaces. It describes *what the user sees and
does*, not the class structure; each section names the implementing widget as
a one-line pointer, no more.

Where a behavior is genuinely ambiguous it is marked `[?]`.

---

## 1. Interface model

- **Type:** terminal UI (TUI). A single full-screen application, no panes or
  tabs — one scrolling chat log with a fixed input bar and status surfaces
  pinned to the bottom.
- **Framework:** [Textual](https://textual.textualize.io) (async-native),
  with Rich for inline rendering (syntax highlighting, diffs, progress bars).
  Slash-command autocomplete uses `textual-autocomplete`.
- **Paradigm:** chat-log. The user types a request; the agent's reply streams
  in as live text that finalizes to rendered Markdown, and the agent's
  actions (tool calls, patch reviews, plans, diagrams) appear as **inline
  cards** interleaved in the same vertical stream. Nothing pops over the chat
  except two modals (full tool-result view, jobs view).
- **Launch:** the console script `code-scalpel` with **no subcommand** opens
  the TUI in the current directory. `code-scalpel --path <dir>` opens it
  elsewhere. (`code-scalpel init` is the separate onboarding command; it does
  not enter the TUI.) Implemented by `ScalpelApp` (`code_scalpel/tui/app.py`),
  launched from `code_scalpel/cli.py`.
- **On exit:** when the app quits it prints a multi-line **session summary**
  to stdout (see §9).
- **Language:** the UI surface is localized (en/ru) via `i18n.py`; the
  default is English, locale resolved from config `ui_locale` then POSIX
  env vars. Hotkey captions, slash-command names, tool names, and file paths
  stay English in every locale. (Some status strings in the cancel/trust
  flows are currently hard-coded Russian — see `[?]` in §5.)

---

## 2. Screen layout

The screen is composed top → bottom (`ScalpelApp.compose`). Regions:

| # | Region | Widget | Always visible? | Shows |
|---|--------|--------|-----------------|-------|
| 1 | **Output log** | `OutputLog` (`output.py`) | yes, fills all spare height (`height: 1fr`) | The scrolling chat: user messages, streamed/finalized model replies (Markdown), status lines, turn-progress lines, turn-summary lines, errors, and all inline cards. |
| 2 | **Input rule** | `Rule` (solid, `#303030`) | yes | A thin horizontal separator above the input. |
| 3 | **Mode input** | `ModeInput` (`input.py`) | yes (height 1) | The single-line prompt `<mode> › ` + the text field. |
| 4 | **Input rule** | `Rule` (solid) | yes | Separator below the input, above the jobs/footer chrome. |
| 5 | **Jobs bar** | `JobsBar` (`jobs_bar.py`) | **collapses to height 0 when idle** | One terse line `⚙ N jobs: kind · kind` when background work is running. |
| 6 | **Status footer** | `StatusFooter` (`footer.py`) | yes (height 1) | Key hints · transient status · trust/thinking/loop/lm-state indicators · context bar · model name. |

A seventh element, the **upward autocomplete dropdown**
(`_UpwardAutoComplete`), is mounted but only visible while typing a slash
command; it opens *above* the input (the input sits at the screen bottom) and
lists matching `/commands`.

**Scroll behavior.** The output log grows bottom-up: new content mounts at the
bottom and the view auto-scrolls to the end on every append. There is a
zero-height spacer (`#_spacer`, `height: 1fr`) as the first child so the first
messages start visually at the bottom and push upward as the conversation
grows. The log is **not** in the Tab focus cycle (`can_focus = False`) but
still responds to PageUp/PageDown and the mouse wheel on hover. Scrollbar is a
1-cell vertical bar in dark grey.

**Startup content** (printed into the log on mount, in order):
1. `● Working directory: <path>`.
2. If `.code-scalpel/TASKS.md` exists with pending tasks: `● Plan: N task(s)
   pending — /go to run`, followed by a **collapsed** `PlanCard`. If a plan
   exists but is fully done: `● Plan: all tasks done`.
3. If the previous session ended mid-patch (`STATE.json` `dirty_patch`): a
   one-time warning that the working tree may have stale edits (suggests
   `git diff` / `git restore .`). The flag is cleared so it nags only once.

---

## 3. Modes

The agent has four **modes**, cycled in this fixed order:

```
ask → plan → code → review → (back to ask)
```

(`_AGENT_MODES = ("ask", "plan", "code", "review")`. A fifth internal mode
`debug` exists for regen retries — see §7 — but it is never in the user-facing
cycle.)

**How mode is shown.** The input prompt prefix is `<mode> › ` and is
**color-coded per mode** (the prefix text *and* the text-cursor cell take the
mode color):

| Mode | Color | Cursor-cell bg | Experiential meaning to the user |
|------|-------|----------------|----------------------------------|
| `ask` | teal cyan `#6bc8d4` | `#3d6b72` | Default, neutral. Ask questions, read code; no edits land without a review gate. |
| `plan` | gold `#d4a050` | `#6b502a` | Thinking / outlining. A plan-mode turn that emits `## T###` headings ends with a **PlanCard** and writes `TASKS.md`. |
| `code` | green `#7fc090` | `#3a6b48` | Action / making changes. Replies that contain SEARCH/REPLACE edit blocks produce an apply gate (or auto-apply, per trust). With the retry loop on, code mode runs the auto apply→test→retry path. |
| `review` | coral `#d97b6c` | `#6b3d36` | Caution / examining. (Same streaming flow as ask; the model is steered toward critique.) |

**How mode is switched:**
- `Ctrl+T` cycles to the next mode (the primary, advertised way — the footer
  hint says so).
- `/mode <m>` sets a specific mode by name (`ask`/`plan`/`code`/`review`);
  invalid names are silently ignored.
- The `/go` flow auto-switches to `code` mode when the user picks "next task"
  or "full plan".

Switching mode repaints the prompt prefix + cursor color and updates the
footer immediately. Mode is session state; it is not persisted across exits.

---

## 4. Trust & thinking indicators

### Trust level

Three levels, cycled with `Ctrl+L` in this order:

```
skeptic → optimist → yolo → (back to skeptic)
```

What it changes experientially:
- **skeptic** — shell commands require an inline confirmation card before
  they run; patch edits land in a review gate; fork/choice prompts wait
  forever (no timeout).
- **optimist** — edits auto-apply without a review card; a status line
  `● Applied N edit(s) (trust=optimist)` reports it. Fork prompts get a
  timeout (the timeout is supplied by the fork policy, not hard-coded in the
  card).
- **yolo** — most aggressive auto-confirm.

The footer always shows the current level as a full word: `skeptic` /
`optimist` / `yolo` (localized; ru renders `yolo` as `банзай`). Cycling prints
a chat status line `● trust: <level> (session-only, resets on exit)`.

A special elevation path: from a skeptic-mode shell confirmation card the user
can pick **`(s) allow for session`**, which silently promotes trust to
`optimist` for the rest of the session and prints
`● trust: оптимист (на сессию — все shell команды авто-разрешены)`. `[?]`
(this status string is hard-coded Russian regardless of locale).

Trust is session state, reset to the configured default on exit.

### Thinking effort

Four levels, cycled with `Ctrl+K`:

```
off → low → medium → high → (back to off)
```

This is **only available when the model supports reasoning params**
(`_supports_thinking`, autodetected at startup from the provider metadata /
name pattern, or pinned by config). If the model does not support it,
`Ctrl+K` does nothing but raise a 2-second notification *"Current model
doesn't support thinking params."*

When supported and not `off`, the footer shows `◐ low` / `◐ med` / `◐ high`.
When `off` or unsupported, the indicator is hidden entirely (no idle noise).

---

## 5. Keybindings

Verified against `ScalpelApp.BINDINGS` and the card-level bindings. All
app-level bindings are `show=False` except Quit, so they do not appear in a
Textual key panel — the footer hint advertises only `[ctrl+t]` and `[ctrl+q]`.

### App-level (global)

| Key | Action | Notes |
|-----|--------|-------|
| `Ctrl+Q` | Quit | Captures a session summary, printed to stdout after the app exits (§9). |
| `Ctrl+T` | Cycle **mode** | ask → plan → code → review → ask. Repaints prompt + footer. |
| `Ctrl+L` | Cycle **trust** | skeptic → optimist → yolo. Prints a chat status line. |
| `Ctrl+K` | Cycle **thinking effort** | off → low → medium → high. No-op + notification if model lacks reasoning support. |
| `Ctrl+O` | Open **last tool result** in a full-screen modal | If no tool result yet: prints `● No tool result yet in this session.` |
| `Ctrl+J` | Open **background jobs** modal | Lists kind · description · age per live job. |
| `Ctrl+Y` | **Copy** focused tool card's raw output to the system clipboard | Must have a `ToolUseCard` focused (via Ctrl+↑/↓); otherwise a 2-s notification tells you to focus a card first. Tries native clipboard, falls back to OSC52. |
| `Ctrl+↑` | Focus **previous (older)** tool card | From the input, jumps to the newest card; from a card, steps toward older. Clamps at the oldest (no wrap). |
| `Ctrl+↓` | Focus **next (newer)** tool card | Stepping past the newest card drops focus back into the input. |
| `Esc` | **Cancel / dismiss** | Context-dependent — see the Esc state machine below. |

`Esc` is also caught at the App's `on_key` level as a fallback, because the
autocomplete sometimes swallows it.

### Esc state machine (cancel / focus / unload)

`Esc` behaves differently depending on what's focused and what's running:

1. **A tool/choice card is focused** → Esc just returns focus to the input
   ("I'm done browsing cards"), it does *not* cancel the running step.
2. **No live step worker** → Esc is inert (disarms any pending guard).
3. **Live step running, first Esc** → *arms* the cancel. Footer shows
   `⚠ ESC ещё раз — отменить задачу` for 2 s, then auto-disarms. `[?]`
   (this guard string is hard-coded Russian.)
4. **Second Esc within the window** → cancels the step worker (Python-side
   connection close). Prints `● Cancelled.` Then a 3-second grace check runs:
   - For **LM Studio**, if the model is confirmed stopped → a quiet
     notification. If status is unknown (`lms` CLI missing) → a warning, no
     further action.
   - If the model is *still generating* after 3 s → the footer arms a
     **force-unload**: `⚠ Модель не отреагировала за 3s. ESC снова →
     выгрузить` for 5 s. `[?]` (hard-coded Russian.)
5. **Third Esc while unload-armed** → forces `lms unload` (loses the warm
   cache, ~5 s reload), with a result notification.
   - For paid/unknown providers there is no busy probe, so only the
     client-side cancel happens, with a warning that billing may continue.

### Input field (HistoryInput)

| Key | Action |
|-----|--------|
| `Enter` | Submit the line (posts a `UserMessage`, records it in history, clears the field). Empty lines are ignored. |
| `↑` / `↓` | **When the autocomplete dropdown is open**: navigate the dropdown. **Otherwise**: bash-style command history — ↑ recalls older entries, ↓ moves forward and restores the in-progress draft when you walk past the newest entry. History is per-session, in-memory, dedups consecutive duplicates and skips empties. |

### Card-level

| Card | Keys |
|------|------|
| `ToolCallCard` (patch review) | `a` apply · `r` reject · `g` regen (only while in `reviewing` state). |
| `ChoiceCard` / `ShellExecCard` | the option keys (e.g. `t`/`p`/`m`, or `a`/`s`/`r`) · `Esc` cancels when `cancel_on_escape` (ShellExecCard disables this so the app's double-Esc guard owns cancel). **RU-layout remap:** a Cyrillic glyph on the same physical QWERTY key is mapped back to its latin twin, so option keys work under a Russian keyboard layout. |
| `ToolUseCard` collapsible title (when focused via Ctrl+↑/↓) | `Enter`/`Space` toggle fold/unfold (Textual `Collapsible` built-in). |
| `ToolResultModal` | `Esc`/`Ctrl+O` close · `Ctrl+C` copy raw output. |
| `JobsModal` | `Esc`/`Ctrl+J` close. |

---

## 6. Slash commands

Typed into the input; dispatched by `ScalpelApp._handle_slash`. The
autocomplete dropdown (opens upward) suggests these as you type `/`. Verified
against `_SLASH_COMMANDS` and the dispatch table.

| Command | User-facing meaning |
|---------|---------------------|
| `/new` | Start a new session — clears the chat log, resets `STATE.json`, clears the agent's history. |
| `/compact` | Summarize conversation history to free up context. No-op with a status if there's nothing to compact. Re-anchors the footer context bar after. |
| `/map [path]` | Project map, same view the model gets: no arg → project file tree; `/map foo.py` → outline of that file (classes/functions/methods/imports); `/map subdir` → tree under a subdir. Renders as a tool card; build runs off the event loop. |
| `/tasks [rm T### \| clear]` | Show the plan as a `PlanCard`; `/tasks rm T001` drops one task; `/tasks clear` deletes `TASKS.md`. |
| `/stats` | Full session stats (model, mode, requests, elapsed, tokens, rate, context, cost) — rendered as a fully-inlined tool card. |
| `/context` | Context-budget breakdown by category (system prompt / tools schema / skills / history) — rendered as a tool card. |
| `/skills` | List built-in tools (with token cost + one-line summary), detected project skills, and the slash-command surface — as a tool card. |
| `/remember <fact>` | Persist one project note; the agent auto-recalls top matches each turn. Confirms `● Remembered: …`. |
| `/recall [query]` | Preview what the agent would recall for `query`; no arg → list all stored notes newest-first. Renders as a tool card. |
| `/go` | If `TASKS.md` exists → mount the **go choice card** (next task / full plan / manual). If no plan → toggle the iterative retry loop and return to input. |
| `/commit-msg` | Draft an imperative commit message from the staged diff (or unstaged if nothing staged); prints it verbatim to copy-paste. |
| `/escalate` | Flush pending forks through the upstream model. No-op (with a status) when no upstream is configured or the queue is empty. |
| `/learn <name> [--url URL]` | Generate a recipe markdown under `.code-scalpel/recipes/`. `/learn skill <name>` generates a skill instead; `/learn recipe <name>` is the explicit recipe form. `--url <url>` fetches a page, converts HTML→Markdown, and feeds it as an authoritative source. Runs off-loop with a footer status + jobs entry. |
| `/help` | List all commands inline (also reminds: Ctrl+T cycles modes, Ctrl+L cycles trust). |
| `/mode <m>` | Set mode by name. Exists, but mode is normally cycled with Ctrl+T. |

Unknown `/xyz` → `Unknown command: /xyz`.

> Note: the `/learn` flags are `--url` and the `skill`/`recipe` sub-kinds —
> there is **no** `--type` flag.

---

## 7. Cards & widgets

Cards are inline, mounted into the chat stream. There are two families:

- **History cards** mount *into the `OutputLog`* (above the input via the
  log's append), stay as a permanent trace, default collapsed/expanded per
  type, and are reachable only via Ctrl+↑/↓ (kept out of the Tab cycle).
- **Action cards** (review/choice/shell/go) mount *before the `ModeInput`*
  (between the log and the input rule), grab focus, and block on a user
  decision; they are removed (or settle to a read-only "done" line) once
  resolved.

### 7.1 ToolUseCard — a completed tool round-trip
*(`tool_use.py`; the workhorse history card.)*

- **Trigger:** every tool the model invokes (`read_file`, `grep`,
  `run_tests`, …) and every synthetic tool surface (`/map`, `/stats`,
  `/context`, `/skills`, `/recall`, patch-attempt renders).
- **Default state:** a **collapsed** one-line header:
  `● name(args) · summary`. The dot is green `#5fbf5f` for ok, red `#bf6060`
  for failure. The summary is tool-specific: `N lines` for read_file,
  `N matches` / `no matches` for grep, first line of output for run_tests,
  line/char count otherwise.
- **Expand:** click the chevron (or focus via Ctrl+↑/↓ then Enter/Space) to
  reveal the body — the first **5 lines** of output, syntax-highlighted for
  successful `read_file` (lexer inferred from the file extension; monokai
  theme), plain otherwise. If more lines were elided: a dim footer `… N more
  lines (Ctrl+O for full view)`.
- **`full=True` mode:** short-by-construction payloads (/stats, /context,
  /skills, /recall) render their whole body inline with no truncation footer.
- **Copy:** focus it and press `Ctrl+Y` to copy the raw output.
- **Visual states:** ok (green dot) / error (red dot). No running state —
  this card is created already-complete.

### 7.2 ToolCallCard — patch review gate
*(`tool_call.py`; an action card.)*

- **Trigger:** in skeptic trust, when a model reply contains SEARCH/REPLACE
  edits, an `Apply` card mounts before the input. Also used as the
  manual-review fallback when the retry loop gives up.
- **States:**
  - `running` — dim spinner `◌ label`, no interaction.
  - `reviewing` — header in mode-blue `◌ Apply`, body shows the **unified
    diff** (Pygments diff lexer: +/- coloring + token highlight), hint row
    `[a] apply · [r] reject · [g] regen`. The card auto-focuses. Footer shows
    `● reviewing`.
  - `done` — green dot `● label` + a dim summary line, read-only,
    un-focusable.
  - `error` — coral dot + `└ Error: …` line, read-only.
- **Interaction:** `a` applies the pending edits (sets/clears `dirty_patch`
  in state around the write), `r` rejects (`Patch rejected.`), `g` asks the
  model to regenerate a different patch (one round, in `debug` sub-mode which
  bumps temperature so the retry diverges). After any choice, focus returns
  to the input.

### 7.3 ChoiceCard — interactive fork / selection
*(`cards/choice.py`; an action card. Base class for ShellExecCard.)*

- **Trigger:** (a) the `/go` mode-selection card; (b) an agent **fork** that
  needs a human decision (`_fork_ui_hook`).
- **Shows:** a titled header `◌ <title>` (mode-blue) and a hint block of
  keyed options. With descriptions, options render one-per-line:
  `(key) label   description`, plus `(esc) cancel`. Without descriptions, a
  single inline row `(key) label · (key) label …`. Option keys are bold
  green.
- **Interaction:** press an option's key to choose; `Esc` cancels (posts
  `chosen_key="esc"`) when `cancel_on_escape` is set. **RU-layout remap**
  applies (Cyrillic→latin physical key). On resolve, the header settles to
  `● <title> — <chosen label>` and the card becomes un-focusable and is
  removed by the app.
- **Timeout:** the *fork* path may pass a timeout (driven by trust policy,
  not the card): `None` → wait forever (skeptic); a number → `asyncio.wait_for`,
  and on expiry the card returns `None` (the forker falls through to its Auto
  choice). The `/go` card has no timeout.
- **`/go` options:** `(t) next task` · `(p) full plan` · `(m) manual`.
  Picking `t`/`p` switches to code mode; `t` runs one task with retries, `p`
  walks all remaining tasks, `m` toggles the manual retry loop.

### 7.4 ShellExecCard — shell confirmation gate
*(`cards/shell_exec.py`; ChoiceCard subclass.)*

- **Trigger:** the agent wants to run `shell_exec` under **skeptic** trust.
  Mounts before the input and auto-focuses; the agent's coroutine blocks on
  an `asyncio.Future` until resolved.
- **Shows:** header `◌ shell_exec`, the command **bash-syntax-highlighted**,
  hint row `(a) approve · (s) allow for session · (r) reject`.
- **Interaction:** `a` approves once; `s` approves *and* elevates trust to
  optimist for the session (so subsequent shell calls auto-run); `r` rejects.
  Settles to `● shell_exec — approved` (green) or `● shell_exec — rejected`
  (coral). `cancel_on_escape=False` — Esc here is owned by the app's
  double-Esc cancel guard, and a cancelled worker rejects the command
  (equivalent to reject).

### 7.5 PlanCard — the TASKS.md plan
*(`plan_card.py`; a history card.)*

- **Trigger:** a plan-mode turn that emits `## T###` headings; `/tasks`; or
  the startup notice (collapsed there).
- **Default:** **expanded** (the plan is the headline artefact of the turn).
- **Header:** `📋 Plan (N tasks)` or `📋 Plan (done/N tasks)`.
- **Body, per task:** `◻ T001: title` (or `✓ T001: title` struck-through
  when done), then dim-labelled `Goal:` / `Files:` / `Acceptance:` bullets /
  `Test:` lines. Completed tasks collapse to just the struck title.
- **Note:** the card is a *renderer* — there are no per-task action buttons
  on it; execution is driven by `/go`.

### 7.6 MermaidCard — rendered diagram
*(`mermaid_card.py`; a history card.)*

- **Trigger:** the model's finalized reply contains a ` ```mermaid ` block.
  Mermaid blocks render **before** any apply card (diagram = context, dialog
  = action).
- **Default:** **expanded**, header `🗺  Mermaid diagram`.
- **Render fallback chain (offline-first):** (0) pure-Python ASCII renderer
  for flowchart / sequenceDiagram / classDiagram — no external binary; (1)
  if that returns nothing and `mmdc` + `rich-pixels` are available → render
  to PNG drawn with Unicode half-blocks; (2) `mmdc` present but fails → raw
  source + one-line error hint; (3) neither → raw source (YAML-highlighted)
  + an install hint. No malformed diagram can crash the TUI. Rendering runs
  off the event loop, swapping a placeholder for the result.

### 7.7 OperationCard — phased operation timeline
*(`cards/operation.py`; focusable card.)*

A unified "something is happening across phases" widget that walks an
operation through `loading → processing → generating → done` (or `error`)
with a live timer and, when the data source provides them, 0..1 **progress
bars** (`▓▓▓░░░ 42%`). Each fired phase renders one line: emoji + label +
detail + bar (active only) + `[time]` + ✓. Ticks at 5 Hz; stops on done/fail
and stays as a browsable trace. Phase emoji: 🔄 loading · 📊 processing ·
💬 generating · ✓ done · ✗ error. `cancel()` marks the current phase as
error (`cancelled`). `[?]` — this card is fully implemented but is **not
wired into the main `_run_step` streaming path** in `app.py` (which uses
`TurnProgress`); it appears reserved for the native LM Studio event path /
upstream-flush operations. A faithful rewrite must keep the widget; whether
it is on the default turn path today is the open question.

### 7.8 ToolResultModal — full result viewer
*(`tool_result_modal.py`; a modal.)*

- **Trigger:** `Ctrl+O` (opens the *last* tool result).
- **Shows:** header `name(args) · ok/failed · N lines · N chars`; a scrollable
  body with the **full** output — syntax-highlighted (with line numbers) for
  `read_file`, custom-highlighted with a line-number gutter for `project_map`,
  plain-with-line-numbers otherwise; hint `[esc] close · [ctrl+c] copy`.
- **Perf:** mounts a `● Rendering…` placeholder instantly and builds the
  heavy renderable off the event loop, so a 200-line body never freezes the
  modal.
- **Keys:** `Esc`/`Ctrl+O` close, `Ctrl+C` copy raw output (native clipboard
  → OSC52 fallback).

### 7.9 JobsBar & JobsModal — background jobs
*(`jobs_bar.py`, `jobs_modal.py`.)*

- **JobsBar:** the inline strip above the footer. Collapsed (height 0,
  `display:none`) when idle; when work runs it shows `⚙ N jobs: kind · kind`
  (kinds only — map / step / compact / commit-msg / learn / run-plan /
  code-retry, etc.). Subscribes to the `JobRegistry`; updates on every
  snapshot.
- **JobsModal:** `Ctrl+J` opens a centered modal listing each live job with
  **kind · age** and a description line under it; `● idle — nothing running.`
  when empty. `Esc`/`Ctrl+J` close. No per-job cancel yet.

### 7.10 TurnProgress — live in-flight turn line
*(`turn_progress.py`.)*

A single ephemeral line mounted in the chat during a streaming turn,
updated ~every 250 ms: `⋯ thinking · 12s · ↓ 340 tokens · 28 tok/s · 🔧 2
tools`. Fields appear only once non-zero (the line starts as just
`⋯ thinking` and grows). Removed when the turn finalizes — replaced by the
permanent turn-summary line.

---

## 8. Streaming & focus model

### Streaming a turn (`_run_step`)

1. On submit, the user line is echoed into the log as `mode › text` (bold).
2. A `TurnProgress` line and an empty streaming `Static` (`msg-stream`, dim)
   are mounted.
3. As the runtime yields items:
   - **TextDelta** → appended to the live Static; the view scrolls to end;
     every >250 ms the TurnProgress line updates (approx tokens via char/4,
     rate, tool count).
   - **ToolExecuted** → the current streamed text finalizes to Markdown, a
     `ToolUseCard` is added for the tool, and a fresh streaming Static opens
     for the continuation. Tool count bumps immediately.
   - **UsageReport** → stashed for the final summary (real token counts).
   - **RetryNotice** → the unread first-attempt text is discarded, a status
     `↻ Re-reading <path> before patching` prints, and streaming restarts.
4. At end, the live Static is swapped for a rendered **Markdown** widget
   (code fences, lists, highlighting). The TurnProgress line is removed and a
   permanent **turn-summary** line prints:
   `⤷ 🔧 N tools · ↓ N tokens · NN tok/s · N.Ns` (tool segment omitted when
   zero).
5. Post-processing on the finalized text: Mermaid blocks render first, then
   edit blocks → apply gate (or auto-apply by trust); in plan mode a
   `## T`-bearing reply appends a PlanCard.

The **code + retry loop** path (`_run_code_with_retry`) streams attempt 1 the
same way (so the user sees tokens during a 30–90 s local generation), then
renders each attempt as a `patch_attempt_N` ToolUseCard whose ok-dot tracks
test pass/fail, and falls back to a manual `Apply` card if it gives up.

### Focus model

- The **input** is the default focus and where the user lives.
- The **OutputLog is not focusable** (deliberately kept out of the Tab
  cycle), and history cards' collapsible titles have `can_focus` turned off
  at mount — so Tab never walks dead history.
- **Ctrl+↑/↓** are the *only* way to move focus into history tool cards.
  Order: older `ToolUseCard`s first, then any awaiting `ChoiceCard`s last
  (so Ctrl+↑ from the input hits the closest pending card first). Stepping
  past the newest returns to the input; stepping before the oldest clamps.
- **Action cards** (review/choice/shell/go) auto-focus when mounted and take
  the relevant single-key bindings while awaiting; resolving them returns
  focus to the input.
- **Esc on a focused card** returns to the input rather than cancelling the
  live step (see §5).

---

## 9. Status & feedback surfaces

### StatusFooter (`footer.py`)

A single bottom line assembled as ` · `-joined segments, in this order:

1. **Key hints** — `[ctrl+t] cycle mode · [ctrl+q] quit` (localized; brackets
   escaped so Rich doesn't eat them).
2. **Transient status** — only meaningful states, e.g. `● reviewing`,
   `● error`, `◌ compacting…`, `◌ patch loop…`, `◌ learning …`,
   `◌ commit-msg…`, plus the Esc/unload guard warnings. No idle/thinking
   noise.
3. **Indicators** (space-joined cluster): **trust** (`skeptic`/`optimist`/
   `yolo`), **thinking** (`◐ low/med/high`, only when supported & not off),
   **loop** (`⟳` when the iterative patch loop is on), **lm-state**
   (`[yellow]● gen[/]` when LM Studio is generating, `[dim]○ idle[/]` when
   idle — hidden for non-LM-Studio providers, polled every ~1.5 s via
   `lms ps`).
4. **Context budget** — `ctx 4k/16k (26%)`, a pre-formatted bar that moves on
   **every keystroke** (continuous state, not just per-turn). Colors shift at
   the configured warn/critical thresholds. Hidden until the context limit is
   known. Built by `Session.context_bar`.
5. **Model name** — dim, right-most. Shows the configured name until startup
   detection resolves the real model id.

> Note: the trust segment shows the **full word** (skeptic/optimist/yolo), not
> the abbreviations `[skp]/[opt]/[ylo]`. (The code comment mentions short
> forms, but the live values come from the i18n catalog, which uses full
> words.)

### In-chat feedback lines

- **`● status`** lines — dim grey `#585858`, for working-dir, plan notices,
  cancellations, applied/rejected patches, etc.
- **`⤷ summary`** lines — brighter `#a0a0a0`, the permanent per-turn cost
  summary and run/upstream summaries.
- **`⋯ progress`** line — dimmer `#808080`, the live ephemeral TurnProgress.
- **error** lines — coral `#bf6060`.

### Exit / session summary

On quit, `on_unmount` captures a multi-line `stats_report` (model / mode /
requests / elapsed / tokens / rate / context / cost) into `_exit_summary`,
which `cli.py` echoes to stdout *after* the TUI closes:
`Session summary:\n<report>`. Any error in building it is swallowed so a
broken summary never blocks exit.

---

## 10. Color & affordance conventions

A rewrite should reproduce these (exact hex pinned in code where shown):

- **Background palette:** app/log bg `#0f0f0f`; panels (footer/jobs/input)
  `#1c1c1c`–`#1a1a1a`; collapsible body `#161616`; borders/rules `#2a2a2a`–
  `#303030`; primary text `#d0d0d0`; dim text `#585858`; muted `#a0a0a0`.
- **Mode colors:** ask `#6bc8d4` · plan `#d4a050` · code `#7fc090` · review
  `#d97b6c` (prompt prefix + cursor cell; cursor uses a ~55%-brightness
  sibling).
- **Semantic accents:** success/green `#7fc090` (and brighter `#5fbf5f` for
  ok-dots); error/coral `#d97b6c` / `#bf6060`; thinking/gold `#d4a050`;
  accent/cyan `#6bc8d4`. Diff add `#7fc090` on `#16241a`, diff del `#d97b6c`
  on `#2a1818`.
- **State dots / spinners:** `◌` = running/awaiting (and the dim spinner on
  running cards); `●` = done/settled; `▶` = operation card title; `✓` /
  `✗` = success / failure markers.
- **Indicator glyphs:** `◐` thinking · `⟳` retry-loop on · `⚙` jobs bar ·
  `🔧` tool count · `↓` tokens · `⋯` live progress · `⤷` turn summary ·
  `↻` re-read/retry · `↷` skipped · `📋` plan · `🗺` mermaid · phase emoji
  🔄/📊/💬 in the operation card.
- **Syntax highlighting themes:** `monokai` for read_file/full-result bodies,
  `ansi_dark` for diffs and shell commands, Pygments `diff` lexer for patches.
- **Scrollbars:** 1-cell vertical, grey track (`#2a2a2a`), brightening on
  hover/active.

---

## 11. Anti-patterns (Textual / this TUI)

- **Don't push rendering into the agent.** `app.py` runs the finalized reply
  through `extract_edits` / `extract_mermaid_blocks` and decides what to draw;
  `agent.py` stays render-free.
- **Don't bypass the single channel.** Every turn goes through
  `Runtime.stream()` → `Session.prepare_turn`; widgets never call
  `StepAgent.stream_ask` directly.
- **Keep history cards out of the focus cycle.** Only the input and the
  active card are focusable; the OutputLog and collapsible titles have
  `can_focus` off so Tab never walks dead history. Ctrl+↑/↓ is the only path
  in.
- **Render untrusted text with `markup=False`.** Model output, file bodies,
  grep matches, plan fields, project-map dumps all contain `[`/`]`/`=` that
  Rich would try to parse — they are rendered with markup disabled or via
  `rich.Text.append` (literal spans). App-owned constants (job kinds, plan
  title) keep markup on.
- **Don't block the event loop.** Every I/O path (LLM, shell, tests, map
  build, mermaid render, modal layout) is async / threaded and
  Esc-cancellable. Heavy renders mount a placeholder first and swap in the
  result.
- **Hook callbacks swallow their own exceptions** so a buggy widget can't
  kill the autonomous run-plan loop.
- **A broken session/exit summary must never block exit** — the capture is
  wrapped and silently skipped on error.
