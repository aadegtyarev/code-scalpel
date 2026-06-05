# UI Guide

> **Status: extractor draft (legacy adoption).** Extracted from
> `code_scalpel/tui/`. `pm-architect` owns the final form.

## Interface type and framework

A **terminal UI (TUI)** built on **Textual** (async-native). Single full
screen app (`ScalpelApp`, `code_scalpel/tui/app.py`), launched by
`code-scalpel` (no subcommand). All output is a vertically-scrolling chat
log; the agent's actions appear as inline cards that stream tokens as they
arrive.

## Main screen structure

Top → bottom (`compose`):

1. **OutputLog** — `VerticalScroll` chat history; messages grow bottom-up.
   Model replies render as Markdown (with syntax-highlighted code and
   rendered ```mermaid``` blocks); tool actions render as cards.
2. **Input rule** (horizontal separator).
3. **ModeInput** — single-line input prefixed with the current mode
   (`> ask`), colour-coded per mode. Slash commands autocomplete via an
   upward-opening dropdown.
4. **JobsBar** — background-job row; collapses to height 0 when idle.
5. **StatusFooter** — context budget bar + %, tokens/sec, model name
   (dim, right), and the mode / trust / thinking indicators.

Navigation model: type to talk to the agent; cycle modes/trust/thinking
with Ctrl keys; focus cycles only between the input and the active
tool/choice card (history cards are quiet, reached via Ctrl+O / Ctrl+up /
Ctrl+down).

## Keybindings

| Key | Action |
|---|---|
| Ctrl+Q | Quit (prints exit/session summary to stdout) |
| Ctrl+T | Cycle mode: ask → plan → code → review |
| Ctrl+L | Cycle trust: skeptic → optimist → yolo |
| Ctrl+K | Cycle thinking effort: off → low → medium → high (only if model supports it) |
| Ctrl+O | Open the last tool result in a modal |
| Ctrl+J | Show background jobs modal |
| Ctrl+Y | Copy focused card output to clipboard |
| Ctrl+↑ / Ctrl+↓ | Focus previous / next tool card |
| Esc | Cancel the active streaming step (double-Esc guard; further Esc can force model unload after a grace period) |

## Slash commands (typed in the input)

`/new` (clear session+state), `/compact` (summarize history), `/map [path]`
(tree / file outline / subdir tree), `/tasks [rm T### | clear]`,
`/stats`, `/context`, `/skills`, `/remember <fact>`, `/recall [query]`,
`/go` (run plan — scope picked via a card), `/commit-msg`, `/escalate`
(flush pending upstream forks), `/learn <name> [--url --type]`, `/help`.
(`/mode <m>` exists but mode is normally cycled with Ctrl+T.)

## Cards (per significant widget)

| Card | Purpose / triggers |
|---|---|
| **ToolCallCard / tool_use** | one tool round-trip; collapsed one-liner (name + summary), expands by chevron; states running/reviewing/done/error |
| **OperationCard** | a streaming model operation |
| **ShellExecCard** (`cards/shell_exec`) | skeptic-mode shell confirmation gate `[a]/[r]/...`; resolves a pending future |
| **ChoiceCard** (`cards/choice`) | fork decision dialog — `[a/b/c…]` options, `[?]` clarify, `[⚡]` delegate-to-auto; trust-aware countdown timer (skeptic ∞ / optimist 120s / yolo+critical 60s). Maps ru-keyboard physical keys back to latin |
| **PlanCard** (`plan_card`) | renders / runs the TASKS plan with `[R]/[A]` |
| **MermaidCard** (`mermaid_card`) | renders an extracted ```mermaid``` block (needs `mmdc`; falls back to source) |
| **JobsBar / JobsModal** | background job progress |
| **TurnProgress** | per-turn progress indicator |
| **ToolResultModal** | full last-tool-result view (Ctrl+O) |

## Visual conventions

- **Mode colours** (prompt prefix + cursor cell, CSS `mode-*`): ask=cyan,
  plan=gold, code=green, review=coral.
- **Trust indicator** (footer): `[skp]` / `[opt]` / `[ylo]`.
- **Thinking indicator**: `◐ low/med/high`, shown only when the model
  supports reasoning params.
- **Status states** (footer): only meaningful states shown (`● reviewing`,
  `● error`, `◌ compacting…`) — no idle/thinking noise.
- UI language is **English only** (i18n strings via `i18n.py`; locale via
  `ui_locale`).

## Anti-patterns (Textual / this TUI)

- Don't push rendering logic into the agent — `app.py` runs the final
  reply text through `extract_edits` / `extract_mermaid_blocks` and decides
  what to draw; `agent.py` stays render-free.
- Don't bypass the single channel: all turns go through
  `Runtime.stream()` → `Session.prepare_turn`, never a direct
  `StepAgent.stream_ask` call from a widget.
- Keep history cards out of the focus cycle — only the input and the active
  card are focusable (prevents Tab from walking dead history).
- Hook callbacks (`on_task_start`/`on_task_end`) must swallow their own
  exceptions so a buggy widget can't kill the autonomous loop.
- Don't block the event loop — every I/O path (LLM, shell, tests) is async
  and ESC-cancellable.
