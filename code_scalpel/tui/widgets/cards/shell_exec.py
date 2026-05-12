"""ShellExecCard — confirm card for `shell_exec` in skeptic trust mode.

Inherits from ChoiceCard; adds bash syntax highlighting for the
command and re-fires ShellExecDecision so the app's async-Future
confirm flow works unchanged.

`cancel_on_escape=False` because the app's double-ESC guard owns
cancellation when a shell confirm is pending.
"""

from __future__ import annotations

from typing import Literal

from rich.syntax import Syntax
from textual.app import ComposeResult
from textual.message import Message
from textual.widgets import Static

from code_scalpel.tui.widgets.cards.choice import ChoiceCard, ChoiceDecision, ChoiceOption

_APPROVE = ChoiceOption("a", "approve")
_SESSION = ChoiceOption("s", "allow for session")
_REJECT = ChoiceOption("r", "reject")


class ShellExecDecision(Message):
    """Posted when the user resolves a shell_exec confirmation."""

    def __init__(self, card_id: int, action: Literal["approve", "reject", "session"]) -> None:
        super().__init__()
        self.card_id = card_id
        self.action = action


class ShellExecCard(ChoiceCard):
    """Inline card asking the user to approve or reject a shell command."""

    def __init__(self, command: str, card_id: int) -> None:
        super().__init__(
            title="shell_exec",
            options=[_APPROVE, _SESSION, _REJECT],
            card_id=card_id,
            cancel_on_escape=False,
        )
        self._command = command

    def _compose_body(self) -> ComposeResult:
        yield Static(
            Syntax(
                self._command,
                "bash",
                theme="ansi_dark",
                background_color="default",
                line_numbers=False,
                word_wrap=True,
            ),
            markup=False,
        )

    def _header_text(self) -> str:
        if self._state == "awaiting":
            return "[bold #3d6b72]◌ shell_exec[/bold #3d6b72]"
        if self._chosen == "a" or self._chosen == "s":
            return "[#7fc090]● shell_exec — approved[/#7fc090]"
        return "[#d97b6c]● shell_exec — rejected[/#d97b6c]"

    def _hint_text(self) -> str:
        if self._state != "awaiting":
            return ""
        return (
            "  [bold #7fc090](a) approve[/bold #7fc090]"
            " [#585858]·[/#585858] "
            "[#7fc090](s) allow for session[/#7fc090]"
            " [#585858]·[/#585858] "
            "[bold #d97b6c](r) reject[/bold #d97b6c]"
        )

    def on_choice_decision(self, msg: ChoiceDecision) -> None:
        if msg.card_id != self._card_id:
            return
        if msg.chosen_key == "a":
            action: Literal["approve", "reject", "session"] = "approve"
        elif msg.chosen_key == "s":
            action = "session"
        else:
            action = "reject"
        self.post_message(ShellExecDecision(self._card_id, action))
        msg.stop()
