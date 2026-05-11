from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Input, Static


class HistoryInput(Input):
    """Single-line input with bash-style ↑/↓ history navigation.

    The textual-autocomplete dropdown that ships with ModeInput hijacks
    the arrow keys: ↓ opens the slash-command list, ↑ steps inside it.
    That's the wrong interaction for a shell-shaped prompt — what we
    actually want is what every Linux terminal does: ↑ recalls the
    previous command, ↓ moves forward through history (and clears when
    you walk past the newest entry). Priority bindings let us intercept
    before the dropdown sees the key.

    History is per-widget instance, in-memory only — bash-history
    persistence across sessions can come later (cheap, but unscoped).
    """

    BINDINGS = [
        Binding("up", "history_prev", "Previous command", show=False, priority=True),
        Binding("down", "history_next", "Next command", show=False, priority=True),
    ]

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        # Most-recent entry is at the END (bash order). _idx is the cursor
        # into history while browsing; None means "not browsing — the
        # current value is the user's live draft".
        self._history: list[str] = []
        self._idx: int | None = None
        # Stash of the in-progress text the user was typing before they
        # started walking back. Restored when they walk past the newest
        # entry — same as bash.
        self._draft: str = ""

    def push_history(self, text: str) -> None:
        """Record a submitted command. Skips empties and consecutive
        duplicates — the bash HISTCONTROL=ignoredups default."""
        text = text.strip()
        if not text:
            return
        if not self._history or self._history[-1] != text:
            self._history.append(text)
        self._idx = None
        self._draft = ""

    def action_history_prev(self) -> None:
        if not self._history:
            return
        if self._idx is None:
            # First step back — remember whatever is currently in the
            # input so we can come back to it.
            self._draft = self.value
            self._idx = len(self._history) - 1
        elif self._idx > 0:
            self._idx -= 1
        self.value = self._history[self._idx]
        self.cursor_position = len(self.value)

    def action_history_next(self) -> None:
        if self._idx is None:
            # Not browsing → nothing meaningful "below" the current
            # draft. Stay quiet rather than opening the autocomplete
            # dropdown the way the default ↓ used to.
            return
        if self._idx < len(self._history) - 1:
            self._idx += 1
            self.value = self._history[self._idx]
        else:
            # Walked past the newest entry — restore draft.
            self._idx = None
            self.value = self._draft
            self._draft = ""
        self.cursor_position = len(self.value)


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
        yield HistoryInput(id="textarea", placeholder="")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        text = event.value.strip()
        if text:
            self.post_message(UserMessage(text))
            # Record BEFORE clearing — the input value is the source of
            # truth, history is just a recall buffer.
            if isinstance(event.input, HistoryInput):
                event.input.push_history(text)
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
    def history(self) -> list[str]:
        """In-memory submitted-command history. Empty until first submit."""
        return list(self.query_one("#textarea", HistoryInput)._history)

    @property
    def prefix(self) -> str:
        return f"{self.mode} › "
