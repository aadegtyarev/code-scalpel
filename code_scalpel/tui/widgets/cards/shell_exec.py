"""ShellExecCard — confirm card for `shell_exec` in skeptic trust mode.

Parallel to `ToolCallCard` for patch apply, but for a single shell
command. Each card carries its own `card_id` so the app can match
the user's [a]/[r] back to the awaiting future when multiple
shell_exec confirms could in theory queue up in one turn.

Message shape:
    ShellExecDecision(card_id=N, action="approve" | "reject")
"""

from __future__ import annotations

from typing import Literal

from rich.syntax import Syntax
from textual.app import ComposeResult
from textual.binding import Binding
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

_RUNNING = "◌"
_DONE = "●"


class ShellExecDecision(Message):
    """Posted when the user resolves a shell_exec confirmation."""

    def __init__(self, card_id: int, action: Literal["approve", "reject"]) -> None:
        super().__init__()
        self.card_id = card_id
        self.action = action


_CardState = Literal["awaiting", "approved", "rejected"]


class ShellExecCard(Widget):
    """Inline card asking the user to approve or reject a shell command.

    The command is rendered with bash syntax highlighting (so pipes,
    quotes, env vars stand out). After resolution the card stays
    visible in `approved` / `rejected` state for one render cycle
    before the app removes it — the user gets visual confirmation of
    their own choice.
    """

    DEFAULT_CSS = """
    ShellExecCard {
        height: auto;
        background: #0f0f0f;
        padding: 0 1;
        margin: 0;
    }
    ShellExecCard .hint {
        color: #585858;
    }
    """

    BINDINGS = [
        Binding("a", "approve", "Approve", show=False),
        Binding("r", "reject", "Reject", show=False),
    ]

    can_focus = True

    _state: reactive[_CardState] = reactive("awaiting")

    def __init__(self, command: str, card_id: int) -> None:
        super().__init__()
        self._command = command
        self._card_id = card_id

    @property
    def card_id(self) -> int:
        return self._card_id

    def compose(self) -> ComposeResult:
        yield Static("", id="card-header")
        yield Static("", id="card-body")
        yield Static("", id="card-hint", classes="hint")

    def on_mount(self) -> None:
        self._refresh_all()
        self.focus()

    def _header_line(self) -> str:
        state = self._state
        if state == "awaiting":
            return f"[bold #3d6b72]{_RUNNING} shell_exec[/bold #3d6b72]"
        if state == "approved":
            return f"[#7fc090]{_DONE}[/#7fc090] shell_exec — approved"
        return f"[#d97b6c]{_DONE}[/#d97b6c] shell_exec — rejected"

    def _body_renderable(self) -> Syntax | str:
        # Render the command as bash so pipes, quotes, env vars highlight.
        # Word-wrap stays on — long commands shouldn't truncate.
        return Syntax(
            self._command,
            "bash",
            theme="ansi_dark",
            background_color="default",
            line_numbers=False,
            word_wrap=True,
        )

    def _hint_markup(self) -> str:
        if self._state == "awaiting":
            return (
                "  [bold #7fc090][[a]] approve[/bold #7fc090]"
                " [#585858]·[/#585858] "
                "[bold #d97b6c][[r]] reject[/bold #d97b6c]"
            )
        return ""

    def _refresh_all(self) -> None:
        self.query_one("#card-header", Static).update(self._header_line())
        self.query_one("#card-body", Static).update(self._body_renderable())
        self.query_one("#card-hint", Static).update(self._hint_markup())

    def action_approve(self) -> None:
        if self._state == "awaiting":
            self._state = "approved"
            self._refresh_all()
            self.can_focus = False
            self.post_message(ShellExecDecision(self._card_id, "approve"))

    def action_reject(self) -> None:
        if self._state == "awaiting":
            self._state = "rejected"
            self._refresh_all()
            self.can_focus = False
            self.post_message(ShellExecDecision(self._card_id, "reject"))

    def on_focus(self) -> None:
        self.add_class("--focused")

    def on_blur(self) -> None:
        self.remove_class("--focused")
