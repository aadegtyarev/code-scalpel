from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding

from code_scalpel.config import AppConfig
from code_scalpel.session import Session
from code_scalpel.state import AgentState
from code_scalpel.tui.widgets.footer import StatusFooter
from code_scalpel.tui.widgets.input import ModeInput, UserMessage
from code_scalpel.tui.widgets.output import OutputLog


class ScalpelApp(App[None]):
    CSS_PATH = ["theme.tcss", "styles.tcss"]

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

    def compose(self) -> ComposeResult:
        yield OutputLog()
        yield ModeInput(mode=self._AGENT_MODES[0])
        yield StatusFooter()

    def on_mount(self) -> None:
        self.query_one(ModeInput).focus()
        self._update_footer()

    def on_user_message(self, message: UserMessage) -> None:
        output = self.query_one(OutputLog)
        footer = self.query_one(StatusFooter)
        mode = self._AGENT_MODES[self._mode_index]
        output.print_user(f"{mode} › {message.text}")
        footer.status = "* Thinking…"
        # Agent processing will be wired here in next step
        footer.status = "● idle"

    def action_cycle_mode(self) -> None:
        self._mode_index = (self._mode_index + 1) % len(self._AGENT_MODES)
        mode = self._AGENT_MODES[self._mode_index]
        self.query_one(ModeInput).set_mode(mode)
        self._update_footer()

    def _update_footer(self) -> None:
        footer = self.query_one(StatusFooter)
        mode = self._AGENT_MODES[self._mode_index]
        limit = self.state.context_limit
        footer.hints = f"[tab] mode ({mode}) · [ctrl+q] quit"
        footer.ctx = f"0k/{limit // 1000}k"
