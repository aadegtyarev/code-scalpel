from __future__ import annotations

import asyncio
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.geometry import Offset, Region, Spacing
from textual.widgets import Markdown, Rule
from textual_autocomplete import AutoComplete, DropdownItem

from code_scalpel.agent import StepAgent, TextDelta, ToolExecuted
from code_scalpel.config import AppConfig, autodetect_context_tokens
from code_scalpel.llm.adapter import ChatResponse, OpenAICompatibleAdapter
from code_scalpel.patch.edit_block import Edit, apply_edits, edits_to_diff, extract_edits
from code_scalpel.session import Session
from code_scalpel.state import AgentState
from code_scalpel.tools.shell import AsyncShellRunner
from code_scalpel.tui.widgets.cards.tool_call import PatchDecision, ToolCallCard
from code_scalpel.tui.widgets.footer import StatusFooter
from code_scalpel.tui.widgets.input import ModeInput, UserMessage
from code_scalpel.tui.widgets.output import OutputLog


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
    ("/help", "list commands"),
    ("/mode ask", "switch to ask mode"),
    ("/mode plan", "switch to plan mode"),
    ("/mode step", "switch to step mode"),
    ("/mode review", "switch to review mode"),
]


class ScalpelApp(App[None]):
    CSS_PATH = ["styles.tcss"]

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit"),
        Binding("shift+tab", "cycle_mode", "Mode", show=False),
        Binding("escape", "cancel_step", "Cancel", show=False),
    ]

    _AGENT_MODES: tuple[str, ...] = ("ask", "plan", "step", "review")

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
        self.run_worker(self._detect_context(), exclusive=False)

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
        except (KeyError, ValueError) as e:
            self.query_one(OutputLog).print_error(f"Config error: {e}")

    async def _detect_context(self) -> None:
        try:
            profile = self.config.current_profile
            tokens = await autodetect_context_tokens(profile)
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
                self.run_worker(self._run_step(text), exclusive=True, group="step"),
            )
        )

    def action_cancel_step(self) -> None:
        w = getattr(self, "_step_worker", None)
        if w is not None and not w.is_finished:
            w.cancel()

    def _handle_slash(self, cmd: str) -> None:
        output = self.query_one(OutputLog)
        if cmd == "/new":
            for child in list(output.children):
                if child.id != "_spacer":
                    child.remove()
            self.session = Session()
            AgentState.reset(self.cwd)
            self.state = AgentState.load(self.cwd)
            self._update_ctx()
            return
        if cmd == "/compact":
            output.print_status("● /compact: not implemented in v0.1.")
            return
        if cmd == "/help":
            lines = "Commands:\n" + "\n".join(f"  {c}  — {d}" for c, d in _SLASH_COMMANDS)
            output.print_status(lines)
            return
        if cmd.startswith("/mode "):
            mode = cmd.removeprefix("/mode ").strip()
            if mode in self._AGENT_MODES:
                self._mode_index = self._AGENT_MODES.index(mode)
                self.query_one(ModeInput).set_mode(mode)
                self._update_footer()
            return
        output.print_status(f"Unknown command: {cmd}")

    async def _run_step(self, task: str) -> None:
        import time

        output = self.query_one(OutputLog)
        footer = self.query_one(StatusFooter)
        assert self._agent is not None

        md = output.print_assistant("")
        try:
            await self._wait_mounted(md)

            full = ""
            chunks = 0
            start = time.monotonic()
            last_tick = start
            async for item in self._agent.stream_ask(task):
                if isinstance(item, TextDelta):
                    full += item.text
                    chunks += 1
                    md.update(full)
                    output.scroll_end(animate=False)
                    now = time.monotonic()
                    if now - last_tick > 0.25:
                        elapsed = now - start
                        if elapsed > 0.1:
                            rate = chunks / elapsed
                            footer.status = f"◌ streaming · {rate:.0f} tok/s"
                        last_tick = now
                elif isinstance(item, ToolExecuted):
                    # Hide the empty Markdown widget that wrapped the tool-call
                    # text (model wrote <TOOL: ...> only) — replace with a card.
                    await md.remove()
                    output.add_tool_use(item.call, item.result)
                    full = ""
                    md = output.print_assistant("")
                    await self._wait_mounted(md)

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

            edits = extract_edits(full)
            if edits:
                await md.remove()
                card = ToolCallCard("Apply", "")
                await self.mount(card, before=self.query_one(ModeInput))
                card.set_reviewing(edits_to_diff(edits, self.cwd))
                self._pending_edits = edits
                footer.status = "● reviewing"
            else:
                rate = self._last_stream_rate
                footer.status = f"● idle · {rate:.0f} tok/s" if rate else "● idle"
        except asyncio.CancelledError:
            output.print_status("● Cancelled.")
            footer.status = "● idle"
            raise
        except Exception as e:
            output.print_error(f"Error: {e}")
            footer.status = "● error"

    async def _wait_mounted(self, widget: Markdown) -> None:
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
            ok, err = apply_edits(self._pending_edits, self.cwd)
            self._pending_edits = None
            if ok:
                output.print_status("● Patch applied.")
                self.state.dirty_patch = True
                self.state.save(self.cwd)
            else:
                output.print_error(f"Apply failed: {err}")
            footer.status = "● idle"

        elif action == "reject":
            self._pending_edits = None
            output.print_status("Patch rejected.")
            footer.status = "● idle"

        elif action == "regen":
            self._pending_edits = None
            output.print_status("Regen not implemented in v0.1.")
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
        footer = self.query_one(StatusFooter)
        limit = self.state.context_limit
        footer.hints = r"\[shift+tab] cycle mode · \[ctrl+q] quit"
        footer.ctx = f"0k/{limit // 1000}k"

    def _update_ctx(self) -> None:
        used = self.session.total_prompt_tokens + self.session.total_completion_tokens
        limit = self.state.context_limit
        ctx = self.session.context_bar(
            used,
            limit,
            self.config.agent.context_budget_warn,
            self.config.agent.context_budget_critical,
        )
        self.query_one(StatusFooter).ctx = ctx
