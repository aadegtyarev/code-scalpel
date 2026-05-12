"""ChoiceCard — universal confirmation/selection card.

Presents a titled list of labelled options with single-key bindings.
Each option has a short key, a label, and an optional description line.

Posts `ChoiceDecision(card_id, chosen_key)` when the user picks an
option.  ESC posts `ChoiceDecision(card_id, "esc")` when
`cancel_on_escape=True` (the default); set it False on cards whose
ESC behaviour is managed by the app (e.g. ShellExecCard, which wants
the double-ESC cancel guard).

`ShellExecCard` inherits from this and overrides `_compose_body`,
`_header_text`, and `_hint_text` for its command-preview look.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from textual.app import ComposeResult
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

_CardState = Literal["awaiting", "done"]


@dataclass(frozen=True)
class ChoiceOption:
    key: str
    label: str
    description: str = ""


class ChoiceDecision(Message):
    """Posted when the user resolves a ChoiceCard."""

    def __init__(self, card_id: int, chosen_key: str) -> None:
        super().__init__()
        self.card_id = card_id
        self.chosen_key = chosen_key


class ChoiceCard(Widget):
    """Inline card with a list of keyed options.

    Subclasses can override `_compose_body`, `_header_text`, and
    `_hint_text` to customise appearance while reusing focus/key/state
    machinery.
    """

    DEFAULT_CSS = """
    ChoiceCard {
        height: auto;
        background: #0f0f0f;
        padding: 0 1;
        margin: 0;
    }
    ChoiceCard .hint {
        color: #585858;
    }
    """

    can_focus = True
    _state: reactive[_CardState] = reactive("awaiting")

    def __init__(
        self,
        title: str,
        options: list[ChoiceOption],
        card_id: int,
        cancel_on_escape: bool = True,
    ) -> None:
        super().__init__()
        self._title = title
        self._options = options
        self._card_id = card_id
        self._cancel_on_escape = cancel_on_escape
        self._chosen: str | None = None

    @property
    def card_id(self) -> int:
        return self._card_id

    def compose(self) -> ComposeResult:
        yield Static("", id="card-header")
        yield from self._compose_body()
        yield Static("", id="card-hint", classes="hint")

    def _compose_body(self) -> ComposeResult:
        return
        yield  # make it a generator

    def on_mount(self) -> None:
        self._refresh()

    def _header_text(self) -> str:
        if self._state == "awaiting":
            return f"[bold #3d6b72]◌ {self._title}[/bold #3d6b72]"
        chosen_label = next(
            (o.label for o in self._options if o.key == self._chosen), self._chosen or ""
        )
        return f"[#a0a0a0]● {self._title} — {chosen_label}[/#a0a0a0]"

    def _hint_text(self) -> str:
        if self._state != "awaiting":
            return ""
        has_descriptions = any(o.description for o in self._options)
        if has_descriptions:
            label_width = max(len(o.label) for o in self._options)
            lines = []
            for opt in self._options:
                key_part = f"[bold #7fc090]({opt.key})[/bold #7fc090]"
                label_part = f"[white]{opt.label:<{label_width}}[/white]"
                desc_part = f"[#585858]{opt.description}[/#585858]"
                lines.append(f"  {key_part} {label_part}   {desc_part}")
            lines.append("  [#585858](esc) cancel[/#585858]")
            return "\n".join(lines)
        # Inline format when no descriptions
        parts = [f"[bold #7fc090]({o.key})[/bold #7fc090] {o.label}" for o in self._options]
        return "  " + " [#585858]·[/#585858] ".join(parts)

    def _refresh(self) -> None:
        self.query_one("#card-header", Static).update(self._header_text())
        self.query_one("#card-hint", Static).update(self._hint_text())

    def watch__state(self, _: _CardState) -> None:
        if not self.is_mounted:
            return
        self._refresh()
        if self._state == "done":
            self.can_focus = False

    def on_key(self, event: object) -> None:
        from textual.events import Key

        if not isinstance(event, Key):
            return
        if self._state != "awaiting":
            return
        for opt in self._options:
            if event.key == opt.key:
                self._resolve(opt.key, event)
                return
        if self._cancel_on_escape and event.key == "escape":
            self._resolve("esc", event)

    def _resolve(self, key: str, event: object) -> None:
        from textual.events import Key

        self._chosen = key
        self._state = "done"
        if isinstance(event, Key):
            event.stop()
        self.post_message(ChoiceDecision(self._card_id, key))

    def on_focus(self) -> None:
        self.add_class("--focused")

    def on_blur(self) -> None:
        self.remove_class("--focused")
