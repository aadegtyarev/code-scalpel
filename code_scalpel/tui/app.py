from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding

from code_scalpel.agent import StepAgent
from code_scalpel.config import AppConfig
from code_scalpel.llm.adapter import OpenAICompatibleAdapter
from code_scalpel.patch.applier import apply_patch
from code_scalpel.session import Session
from code_scalpel.state import AgentState
from code_scalpel.tools.shell import AsyncShellRunner
from code_scalpel.tui.widgets.cards.tool_call import PatchDecision, ToolCallCard
from code_scalpel.tui.widgets.footer import StatusFooter
from code_scalpel.tui.widgets.input import ModeInput, UserMessage
from code_scalpel.tui.widgets.output import OutputLog


class ScalpelApp(App[None]):
    CSS_PATH = ["styles.tcss"]

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit"),
        Binding("tab", "cycle_mode", "Mode", show=False),
    ]

    _AGENT_MODES: tuple[str, ...] = ("ask", "plan", "step", "review")

    def __init__(self, config: AppConfig, cwd: Path = Path(".")) -> None:
        super().__init__()
        self.config = config
        self.cwd = cwd
        self.session = Session()
        self.state = AgentState.load(cwd)
        self._mode_index = 0
        self._pending_patch: str | None = None
        self._runner = AsyncShellRunner()
        self._agent: StepAgent | None = None

    # ── compose ───────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield OutputLog()
        yield ModeInput(mode=self._AGENT_MODES[0])
        yield StatusFooter()

    def on_mount(self) -> None:
        self.query_one(ModeInput).focus()
        self._update_footer()
        self._init_agent()

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

    # ── user message ──────────────────────────────────────────────────────────

    def on_user_message(self, message: UserMessage) -> None:
        mode = self._AGENT_MODES[self._mode_index]
        output = self.query_one(OutputLog)
        output.print_user(f"{mode} › {message.text}")

        if self._agent is None:
            output.print_error("No LLM configured — check config.")
            return

        self.query_one(StatusFooter).status = "◌ thinking…"
        self.run_worker(self._run_step(message.text), exclusive=True)

    async def _run_step(self, task: str) -> None:
        output = self.query_one(OutputLog)
        footer = self.query_one(StatusFooter)
        assert self._agent is not None

        try:
            result = await self._agent.ask(task)
            self.session.record(result.response)
            self._update_ctx()

            if result.patch:
                card = ToolCallCard("Apply", "")
                await self.mount(card, before=self.query_one(ModeInput))
                card.set_reviewing(result.patch)
                self._pending_patch = result.patch
                footer.status = "● reviewing"
            else:
                output.print_assistant(result.reply)
                footer.status = "● idle"
        except Exception as e:
            output.print_error(f"Error: {e}")
            footer.status = "● error"

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

        if action == "apply" and self._pending_patch:
            footer.status = "◌ applying…"
            result = await apply_patch(self._pending_patch, self._runner, self.cwd)
            self._pending_patch = None
            if result.ok:
                output.print_status("● Patch applied.")
                self.state.dirty_patch = True
                self.state.save(self.cwd)
            else:
                output.print_error(f"Apply failed:\n{result.stdout}")
            footer.status = "● idle"

        elif action == "reject":
            self._pending_patch = None
            output.print_status("Patch rejected.")
            footer.status = "● idle"

        elif action == "regen":
            self._pending_patch = None
            output.print_status("Regen not implemented in v0.1.")
            footer.status = "● idle"

        self.query_one(ModeInput).focus()

    # ── mode cycling ──────────────────────────────────────────────────────────

    def action_cycle_mode(self) -> None:
        self._mode_index = (self._mode_index + 1) % len(self._AGENT_MODES)
        mode = self._AGENT_MODES[self._mode_index]
        self.query_one(ModeInput).set_mode(mode)
        self._update_footer()

    # ── footer helpers ────────────────────────────────────────────────────────

    def _update_footer(self) -> None:
        footer = self.query_one(StatusFooter)
        mode = self._AGENT_MODES[self._mode_index]
        limit = self.state.context_limit
        footer.hints = f"[tab] mode ({mode}) · [ctrl+q] quit"
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
