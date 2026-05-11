from __future__ import annotations

from textual.app import ComposeResult
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Input, Static


class UserMessage(Message):
    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text


_MODE_COLORS: dict[str, str] = {
    "ask": "#6bc8d4",  # teal cyan — neutral, default
    "plan": "#d4a050",  # gold — thinking / outlining
    "code": "#7fc090",  # green — action / making changes
    "review": "#d97b6c",  # coral — caution / examining
}

# Darkened siblings of _MODE_COLORS (≈55% brightness) — used as the
# cursor-cell background so the cursor reads as "the same mode" without
# competing with the prompt text for attention.
_MODE_CURSOR_COLORS: dict[str, str] = {
    "ask": "#3d6b72",
    "plan": "#6b502a",
    "code": "#3a6b48",
    "review": "#6b3d36",
}


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
        color: #6bc8d4;
        text-style: bold;
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
    ModeInput.mode-ask Input > .input--cursor {
        background: #3d6b72;
        color: #ffffff;
    }
    ModeInput.mode-plan Input > .input--cursor {
        background: #6b502a;
        color: #ffffff;
    }
    ModeInput.mode-code Input > .input--cursor {
        background: #3a6b48;
        color: #ffffff;
    }
    ModeInput.mode-review Input > .input--cursor {
        background: #6b3d36;
        color: #ffffff;
    }
    """

    def __init__(self, mode: str = "ask") -> None:
        super().__init__()
        self.mode = mode
        self.add_class(f"mode-{mode}")

    def _prompt_str(self) -> str:
        color = _MODE_COLORS.get(self.mode, "#6bc8d4")
        return f"[{color}]{self.mode} ›[/] "

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
        for m in _MODE_COLORS:
            self.remove_class(f"mode-{m}")
        self.add_class(f"mode-{mode}")
        self.mode = mode
        self.query_one("#prompt", Static).update(self._prompt_str())

    def focus_input(self) -> None:
        self.query_one("#textarea", Input).focus()

    @property
    def prefix(self) -> str:
        return f"{self.mode} › "
