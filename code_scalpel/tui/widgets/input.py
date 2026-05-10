from __future__ import annotations

from textual.app import ComposeResult
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Input, Static


class UserMessage(Message):
    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text


class ModeInput(Widget):
    """Single-line input bar: '<mode> › <text>'. Enter submits."""

    DEFAULT_CSS = """
    ModeInput {
        height: 1;
        background: #1a1a1a;
        padding: 0;
        layout: horizontal;
    }
    ModeInput #prompt {
        width: auto;
        height: 1;
        color: #3d6b72;
        padding: 0 0 0 1;
        background: #1a1a1a;
    }
    ModeInput Input {
        width: 1fr;
        height: 1;
        min-height: 1;
        background: #1a1a1a;
        border: none;
        padding: 0;
        color: #d0d0d0;
    }
    ModeInput Input:focus {
        background: #1a1a1a;
        border: none;
    }
    ModeInput Input > .input--cursor {
        background: #3d6b72;
        color: #ffffff;
    }
    """

    def __init__(self, mode: str = "ask") -> None:
        super().__init__()
        self.mode = mode

    def _prompt_str(self) -> str:
        return f"{self.mode} › "

    def compose(self) -> ComposeResult:
        yield Static(self._prompt_str(), id="prompt")
        yield Input(id="textarea", placeholder="")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        text = event.value.strip()
        if text:
            self.post_message(UserMessage(text))
            event.input.value = ""

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.query_one("#prompt", Static).update(self._prompt_str())

    def focus_input(self) -> None:
        self.query_one("#textarea", Input).focus()

    @property
    def prefix(self) -> str:
        return f"{self.mode} › "
