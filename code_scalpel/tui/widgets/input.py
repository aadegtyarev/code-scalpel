from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.message import Message
from textual.widget import Widget
from textual.widgets import TextArea


class UserMessage(Message):
    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text


class ModeInput(Widget):
    """Multiline input with mode prefix. Never blocks — queues messages."""

    DEFAULT_CSS = """
    ModeInput {
        height: auto;
        min-height: 3;
        max-height: 12;
        background: #1c1c1c;
        border-top: solid #2a2a2a;
        border-bottom: solid #2a2a2a;
        padding: 0 1;
    }
    ModeInput TextArea {
        height: auto;
        min-height: 1;
        background: #1c1c1c;
        border: none;
        padding: 0;
    }
    """

    BINDINGS = [
        Binding("ctrl+j,enter", "submit", "Submit", show=False),
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(self, mode: str = "ask") -> None:
        super().__init__()
        self.mode = mode

    def compose(self) -> ComposeResult:
        ta = TextArea(id="textarea")
        ta.show_line_numbers = False
        yield ta

    def action_submit(self) -> None:
        ta = self.query_one("#textarea", TextArea)
        text = ta.text.strip()
        if text:
            self.post_message(UserMessage(text))
            ta.clear()

    def action_cancel(self) -> None:
        self.app.exit()

    def set_mode(self, mode: str) -> None:
        self.mode = mode

    @property
    def prefix(self) -> str:
        return f"{self.mode} › "
