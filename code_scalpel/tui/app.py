from __future__ import annotations

import asyncio
from pathlib import Path

from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.geometry import Offset, Region, Spacing
from textual.widget import Widget
from textual.widgets import Rule
from textual_autocomplete import AutoComplete, DropdownItem

from code_scalpel.agent import StepAgent, TextDelta, ToolExecuted
from code_scalpel.config import AppConfig, autodetect_context_tokens, resolve_model_name
from code_scalpel.llm.adapter import ChatResponse, OpenAICompatibleAdapter
from code_scalpel.patch.edit_block import Edit, apply_edits, edits_to_diff, extract_edits
from code_scalpel.session import Session
from code_scalpel.state import AgentState
from code_scalpel.tools.agent_tools import ToolResult
from code_scalpel.tools.shell import AsyncShellRunner
from code_scalpel.tui.widgets.cards.tool_call import PatchDecision, ToolCallCard
from code_scalpel.tui.widgets.footer import StatusFooter
from code_scalpel.tui.widgets.input import ModeInput, UserMessage
from code_scalpel.tui.widgets.output import OutputLog
from code_scalpel.tui.widgets.tool_result_modal import ToolResultModal


class _UpwardAutoComplete(AutoComplete):
    """AutoComplete that opens above the target — input sits at the screen bottom."""

    def _align_to_target(self) -> None:
        x, y = self.target.cursor_screen_offset
        width, height = self.option_list.outer_size
        new_y = max(0, y - height)
        rx, ry, _w, _h = Region(x - 1, new_y, width, height).constrain(
            "inside",
            "none",
            Spacing.all(0),
            self.screen.scrollable_content_region,
        )
        self.absolute_offset = Offset(rx, ry)


_SLASH_COMMANDS: list[tuple[str, str]] = [
    ("/new", "start a new session — clear chat and reset state"),
    ("/compact", "summarize history to free up context (not yet)"),
    ("/map", "show the project map the model receives each turn"),
    ("/help", "list commands"),
    ("/mode ask", "switch to ask mode"),
    ("/mode plan", "switch to plan mode"),
    ("/mode code", "switch to code mode"),
    ("/mode review", "switch to review mode"),
]


def _format_turn_summary(
    *,
    tool_calls: int,
    rate: float,
    completion_tokens: int,
    duration: float,
    ctx_used: int,
    ctx_limit: int,
) -> str:
    """One-line summary printed inline after each turn — Claude-Code style.
    Replaces the old footer overload; the footer only carries state now.

    Tools / no-tools warning is surfaced so the user can spot ungrounded
    replies. Tokens / rate / duration / ctx round out the cost picture
    without dragging the user back to the bottom of the screen."""
    parts: list[str] = []
    if tool_calls == 0:
        parts.append("[yellow]⚠ no tools used[/yellow]")
    else:
        noun = "tool" if tool_calls == 1 else "tools"
        parts.append(f"🔧 {tool_calls} {noun}")
    if completion_tokens:
        parts.append(f"↓ {completion_tokens} tokens")
    if rate:
        parts.append(f"{rate:.0f} tok/s")
    if duration > 0:
        parts.append(f"{duration:.1f}s")
    if ctx_limit:
        pct = ctx_used / ctx_limit * 100
        parts.append(f"ctx {ctx_used // 1000}k/{ctx_limit // 1000}k ({pct:.0f}%)")
    return "[dim]⤷ " + " · ".join(parts) + "[/dim]"


class ScalpelApp(App[None]):
    CSS_PATH = ["styles.tcss"]

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit"),
        Binding("ctrl+t", "cycle_mode", "Mode", show=False),
        Binding("ctrl+o", "show_last_tool_result", "Open last tool result", show=False),
        Binding("escape", "cancel_step", "Cancel", show=False),
    ]

    _AGENT_MODES: tuple[str, ...] = ("ask", "plan", "code", "review")

    def __init__(self, config: AppConfig, cwd: Path = Path(".")) -> None:
        super().__init__()
        self.config = config
        self.cwd = cwd
        self.session = Session()
        self.state = AgentState.load(cwd)
        self._mode_index = 0
        self._pending_edits: list[Edit] | None = None
        self._last_stream_rate: float = 0.0
        self._runner = AsyncShellRunner()
        self._agent: StepAgent | None = None
        # Latest tool round-trip from the agent — Ctrl+O opens it in a modal.
        self._last_tool_result: ToolResult | None = None

    # ── compose ───────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield OutputLog()
        yield Rule(line_style="solid", classes="input-rule")
        yield ModeInput(mode=self._AGENT_MODES[0])
        yield Rule(line_style="solid", classes="input-rule")
        yield StatusFooter()
        yield _UpwardAutoComplete(
            target="#textarea",
            candidates=[DropdownItem(cmd) for cmd, _ in _SLASH_COMMANDS],
            prevent_default_enter=False,
        )

    def on_mount(self) -> None:
        self.query_one(ModeInput).focus_input()
        self._update_footer()
        self._init_agent()
        self._show_resume_notice()
        self.run_worker(self._detect_context(), exclusive=False)

    async def on_unmount(self) -> None:
        """Print a session summary to stdout on exit — handy for cost tracking."""
        try:
            line = self.session.summary_line()
        except Exception:
            return
        # Stored for the user to read after the TUI exits; printed by main().
        self._exit_summary = line

    _exit_summary: str | None = None

    def _show_resume_notice(self) -> None:
        """If STATE.json reports an interrupted session, surface that inline so
        the user knows they may need to roll back uncommitted changes."""
        if self.state.dirty_patch:
            output = self.query_one(OutputLog)
            output.print_status(
                "● Previous session ended with an unfinished patch. "
                "Working tree may have stale edits — review with `git diff` "
                "or `git restore .` if you want to discard them."
            )
            # Clear the flag so we don't nag every launch
            self.state.dirty_patch = False
            self.state.save(self.cwd)

    def _init_agent(self) -> None:
        try:
            profile = self.config.current_profile
            llm = OpenAICompatibleAdapter(
                base_url=f"{profile.provider_base_url()}/v1",
                api_key=profile.api_key(),
                model=profile.model,
                timeout=float(self.config.agent.llm_timeout),
                cost_per_1k=profile.cost_per_1k,
            )
            self._agent = StepAgent(llm=llm, cwd=self.cwd, config=self.config)
            # Footer shows configured name until resolve_model_name finishes.
            self.query_one(StatusFooter).model = profile.model
        except (KeyError, ValueError) as e:
            self.query_one(OutputLog).print_error(f"Config error: {e}")

    async def _detect_context(self) -> None:
        """One-shot startup discovery: model name and context window. Both
        come from the same /v1/models endpoint, so we do them together —
        cuts the round-trip count in half and keeps the footer's two
        right-side fields in sync."""
        try:
            profile = self.config.current_profile
            model_name = await resolve_model_name(profile)
            tokens = await autodetect_context_tokens(profile)
            footer = self.query_one(StatusFooter)
            footer.model = model_name
            # Adapter was built with profile.model (likely "auto"); replace
            # so the next request carries the real id and logs cleanly.
            if self._agent is not None and model_name != profile.model:
                self._agent._llm._model = model_name  # type: ignore[attr-defined]
            if tokens:
                self.state.context_limit = tokens
                self._update_footer()
        except Exception:
            pass

    # ── user message ──────────────────────────────────────────────────────────

    def on_user_message(self, message: UserMessage) -> None:
        mode = self._AGENT_MODES[self._mode_index]
        output = self.query_one(OutputLog)
        output.print_user(f"{mode} › {message.text}")
        if not message.text.startswith("/"):
            self.session.detect_and_pin_language(message.text)

        if message.text.startswith("/"):
            self._handle_slash(message.text.strip())
            return

        if self._agent is None:
            output.print_error("No LLM configured — check config.")
            return

        self.query_one(StatusFooter).status = "◌ thinking…"
        lang = self.session.user_language or "English"
        text = f"{message.text}\n\n(Reply in {lang}.)"
        # Defer worker until after refresh so the user message lands first
        self.call_after_refresh(
            lambda: setattr(
                self,
                "_step_worker",
                self.run_worker(self._run_step(text, mode=mode), exclusive=True, group="step"),
            )
        )

    async def _do_compact(self) -> None:
        output = self.query_one(OutputLog)
        footer = self.query_one(StatusFooter)
        assert self._agent is not None
        footer.status = "◌ compacting…"
        try:
            summary = await self._agent.compact()
        except Exception as e:
            output.print_error(f"Compact failed: {e}")
            footer.status = "● error"
            return
        if summary is None:
            output.print_status("Nothing to compact.")
        else:
            output.print_status(f"● Compacted. Summary:\n{summary}")
            # Anchor the footer budget to "post-compact" so the bar drops.
            self.session.mark_compacted()
            self._update_ctx()
        footer.status = "● idle"

    def action_cancel_step(self) -> None:
        w = getattr(self, "_step_worker", None)
        if w is not None and not w.is_finished:
            w.cancel()

    def action_show_last_tool_result(self) -> None:
        """Ctrl+O: open the most recent tool result in a modal with full
        content and syntax highlighting. Plan §v0.3 hook."""
        if self._last_tool_result is None:
            self.query_one(OutputLog).print_status("● No tool result yet in this session.")
            return
        self.push_screen(ToolResultModal(self._last_tool_result))

    def on_key(self, event: events.Key) -> None:
        """textual-autocomplete sometimes swallows Escape even when its
        dropdown is hidden. Catch it at the App level as a fallback."""
        if event.key == "escape":
            self.action_cancel_step()

    def _handle_slash(self, cmd: str) -> None:
        output = self.query_one(OutputLog)
        if cmd == "/new":
            for child in list(output.children):
                if child.id != "_spacer":
                    child.remove()
            self.session = Session()
            AgentState.reset(self.cwd)
            self.state = AgentState.load(self.cwd)
            if self._agent is not None:
                self._agent.clear_history()
            self._update_ctx()
            return
        if cmd == "/compact":
            if self._agent is None:
                output.print_error("No LLM configured.")
                return
            if not self._agent.history:
                output.print_status("Nothing to compact yet.")
                return
            self.run_worker(self._do_compact(), exclusive=True, group="step")
            return
        if cmd == "/help":
            lines = "Commands:\n" + "\n".join(f"  {c}  — {d}" for c, d in _SLASH_COMMANDS)
            output.print_status(lines)
            return
        if cmd == "/map":
            from code_scalpel.project_map import build_map

            text = build_map(self.cwd)
            line_count = text.count("\n") + 1 if text else 0
            char_count = len(text)
            output.print_status(
                f"● Project map ({line_count} lines, {char_count} chars — "
                f"sent to the model on every turn):\n{text}"
            )
            return
        if cmd.startswith("/mode "):
            mode = cmd.removeprefix("/mode ").strip()
            if mode in self._AGENT_MODES:
                self._mode_index = self._AGENT_MODES.index(mode)
                self.query_one(ModeInput).set_mode(mode)
                self._update_footer()
            return
        output.print_status(f"Unknown command: {cmd}")

    async def _run_step(self, task: str, *, mode: str = "ask") -> None:
        import time

        output = self.query_one(OutputLog)
        footer = self.query_one(StatusFooter)
        assert self._agent is not None

        placeholder = output.start_streaming()
        try:
            await self._wait_mounted(placeholder)

            full = ""
            chunks = 0
            tool_calls = 0
            start = time.monotonic()
            last_tick = start
            async for item in self._agent.stream_ask(task, mode=mode):
                if isinstance(item, TextDelta):
                    full += item.text
                    chunks += 1
                    placeholder.update(full)
                    output.scroll_end(animate=False)
                    now = time.monotonic()
                    if now - last_tick > 0.25:
                        elapsed = now - start
                        if elapsed > 0.1:
                            rate = chunks / elapsed
                            footer.status = f"◌ streaming · {rate:.0f} tok/s"
                        last_tick = now
                elif isinstance(item, ToolExecuted):
                    tool_calls += 1
                    self._last_tool_result = item.result
                    placeholder.update(full)
                    await output.finalize_streaming(placeholder, full)
                    output.add_tool_use(item.call, item.result)
                    full = ""
                    placeholder = output.start_streaming()
                    await self._wait_mounted(placeholder)
            # Final render: swap the streaming Static for a Markdown widget so
            # code fences and lists render properly.
            md = await output.finalize_streaming(placeholder, full)

            total_elapsed = time.monotonic() - start
            self._last_stream_rate = chunks / total_elapsed if total_elapsed > 0 else 0.0

            # Track session usage (approximate — streaming has no usage payload).
            self.session.record(
                ChatResponse(
                    content=full,
                    prompt_tokens=len(task) // 4 + 1000,
                    completion_tokens=len(full) // 4,
                    cost=None,
                )
            )
            self._update_ctx()

            # Inline turn summary — replaces the old crowded footer. Mounted
            # for every completed turn, before any review/apply card.
            summary = _format_turn_summary(
                tool_calls=tool_calls,
                rate=self._last_stream_rate,
                completion_tokens=len(full) // 4,
                duration=total_elapsed,
                ctx_used=self.session.context_used_tokens,
                ctx_limit=self.state.context_limit,
            )
            output.print_status(summary)

            edits = extract_edits(full)
            if edits:
                await md.remove()
                card = ToolCallCard("Apply", "")
                await self.mount(card, before=self.query_one(ModeInput))
                card.set_reviewing(edits_to_diff(edits, self.cwd))
                self._pending_edits = edits
                footer.status = "● reviewing"
            else:
                footer.status = "● idle"
        except asyncio.CancelledError:
            output.print_status("● Cancelled.")
            footer.status = "● idle"
            raise
        except Exception as e:
            output.print_error(f"Error: {e}")
            footer.status = "● error"

    async def _regenerate(self, prev_edits: list[Edit]) -> None:
        """Ask the model to retry the patch — used after a rejected or
        failed apply. Builds a context message with what was tried."""
        footer = self.query_one(StatusFooter)
        assert self._agent is not None
        footer.status = "◌ regenerating…"
        from code_scalpel.patch.edit_block import edits_to_diff

        diff = edits_to_diff(prev_edits, self.cwd)
        task = (
            "Your previous patch was rejected or didn't apply. Try a different "
            "approach. Previous attempt:\n\n" + diff
        )
        # debug sub-mode bumps temperature so the retry actually diverges from
        # the original attempt instead of regenerating something near-identical.
        self.run_worker(self._run_step(task, mode="debug"), exclusive=True, group="step")

    async def _wait_mounted(self, widget: Widget) -> None:
        # widget.mount is dispatched via a worker in OutputLog._append.
        # Wait a short tick so update() doesn't race the mount.
        from asyncio import sleep

        for _ in range(20):
            if widget.is_mounted:
                return
            await sleep(0.02)

    # ── patch decision ────────────────────────────────────────────────────────

    def on_patch_decision(self, msg: PatchDecision) -> None:
        self.run_worker(self._handle_decision(msg.action), exclusive=True)

    async def _handle_decision(self, action: str) -> None:
        output = self.query_one(OutputLog)
        footer = self.query_one(StatusFooter)

        try:
            card = self.query_one(ToolCallCard)
            await card.remove()
        except Exception:
            pass

        if action == "apply" and self._pending_edits:
            footer.status = "◌ applying…"
            self.state.dirty_patch = True
            self.state.save(self.cwd)
            ok, err = apply_edits(self._pending_edits, self.cwd)
            self._pending_edits = None
            if ok:
                output.print_status("● Patch applied.")
                self.state.dirty_patch = False
                self.state.save(self.cwd)
            else:
                output.print_error(f"Apply failed: {err}")
            footer.status = "● idle"

        elif action == "reject":
            self._pending_edits = None
            output.print_status("Patch rejected.")
            footer.status = "● idle"

        elif action == "regen":
            edits = self._pending_edits
            self._pending_edits = None
            if edits is None or self._agent is None:
                footer.status = "● idle"
            else:
                # Debug retry: feed the apply error back to the model and ask
                # for a fixed patch. One round only — don't spiral.
                self.run_worker(self._regenerate(edits), exclusive=True, group="step")
                return
            footer.status = "● idle"

        self.query_one(ModeInput).focus_input()

    # ── mode cycling ──────────────────────────────────────────────────────────

    def action_cycle_mode(self) -> None:
        self._mode_index = (self._mode_index + 1) % len(self._AGENT_MODES)
        mode = self._AGENT_MODES[self._mode_index]
        self.query_one(ModeInput).set_mode(mode)
        self._update_footer()

    # ── footer helpers ────────────────────────────────────────────────────────

    def _update_footer(self) -> None:
        """Footer is minimal — hints + status + model. Per-turn metrics live
        inline in the chat now (see _format_turn_summary)."""
        footer = self.query_one(StatusFooter)
        footer.hints = r"\[ctrl+t] cycle mode · \[ctrl+q] quit"

    def _update_ctx(self) -> None:
        """No-op kept for callsite compatibility — context usage is shown in
        the inline turn summary instead of the footer now. Callers like
        /compact still invoke it; we no longer touch the footer."""
        return
