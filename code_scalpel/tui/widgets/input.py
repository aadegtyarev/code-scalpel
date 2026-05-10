from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.events import Key
from textual.message import Message
from textual.widget import Widget
from textual.widgets import TextArea


class UserMessage(Message):
    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text


class InputArea(TextArea):
    """TextArea: Enter submits, Ctrl+Enter inserts newline."""

    DEFAULT_CSS = """
    InputArea {
        height: auto;
        min-height: 1;
        background: #1a1a1a;
        border: none;
        padding: 0;
        color: #d0d0d0;
    }
    InputArea:focus {
        height: auto;
        border: none;
    }
    """

    def _on_key(self, event: Key) -> None:
        if event.key == "enter":
            event.prevent_default()
            event.stop()
            assert isinstance(self.parent, ModeInput)
            self.parent.action_submit()
        elif event.key == "ctrl+j":
            event.prevent_default()
            event.stop()
            self.insert("\n")


class ModeInput(Widget):
    """Multiline input with mode prefix. Never blocks — queues messages."""

    DEFAULT_CSS = """
    ModeInput {
        height: auto;
        min-height: 3;
        max-height: 12;
        background: #1a1a1a;
        border: tall #505050;
        padding: 0 1;
        color: #d0d0d0;
    }
    ModeInput:focus-within {
        border: tall #3d6b72;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(self, mode: str = "ask") -> None:
        super().__init__()
        self.mode = mode

    def compose(self) -> ComposeResult:
        ta = InputArea(id="textarea")
        ta.show_line_numbers = False
        yield ta

    def on_mount(self) -> None:
        self.border_title = self.mode

    def action_submit(self) -> None:
        ta = self.query_one("#textarea", InputArea)
        text = ta.text.strip()
        if text:
            self.post_message(UserMessage(text))
            ta.clear()

    def action_cancel(self) -> None:
        self.app.exit()

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.border_title = mode

    @property
    def prefix(self) -> str:
        return f"{self.mode} › "
