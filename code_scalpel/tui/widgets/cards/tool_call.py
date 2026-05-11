from __future__ import annotations

from typing import Literal

from rich.console import RenderableType
from rich.syntax import Syntax
from textual.app import ComposeResult
from textual.binding import Binding
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

_RUNNING = "◌"
_DONE = "●"


def _render_diff(diff: str) -> RenderableType:
    """Render a unified diff with Pygments' diff lexer — gets +/- coloring AND
    Python token highlighting within each code line."""
    return Syntax(
        diff,
        "diff",
        theme="ansi_dark",
        background_color="default",
        line_numbers=False,
        word_wrap=True,
    )


class PatchDecision(Message):
    """Posted when the user resolves a patch review."""

    def __init__(self, action: Literal["apply", "reject", "regen"]) -> None:
        super().__init__()
        self.action = action


_CardState = Literal["running", "reviewing", "done", "error"]


class ToolCallCard(Widget):
    """Inline card showing a tool call status and optional patch review.

    States:
      running   — spinner, no interaction
      reviewing — diff visible, [a]/[r]/[g] active
      done      — green dot, summary line, read-only
      error     — red dot, error line, read-only
    """

    DEFAULT_CSS = """
    ToolCallCard {
        height: auto;
        background: #0f0f0f;
        padding: 0 1;
        margin: 0;
    }
    ToolCallCard .hint {
        color: #585858;
    }
    """

    BINDINGS = [
        Binding("a", "apply", "Apply", show=False),
        Binding("r", "reject", "Reject", show=False),
        Binding("g", "regen", "Regen", show=False),
    ]

    can_focus = True

    _state: reactive[_CardState] = reactive("running")

    def __init__(self, tool: str, args: str = "") -> None:
        super().__init__()
        self._tool = tool
        self._args = args
        self._diff = ""
        self._summary = ""
        self._error = False

    # ── composition ──────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Static("", id="card-header")
        yield Static("", id="card-body")
        yield Static("", id="card-hint", classes="hint")

    def on_mount(self) -> None:
        self._refresh_all()

    # ── public API ───────────────────────────────────────────────────────────

    def set_reviewing(self, diff: str) -> None:
        self._diff = diff
        self._state = "reviewing"
        self._refresh_all()
        self.focus()

    def set_done(self, summary: str, *, error: bool = False) -> None:
        self._summary = summary
        self._error = error
        self._state = "error" if error else "done"
        self._refresh_all()
        self.can_focus = False

    # ── state rendering ──────────────────────────────────────────────────────

    def _header_line(self) -> str:
        label = f"{self._tool}({self._args})" if self._args else self._tool
        state = self._state
        if state == "running":
            return f"[dim]{_RUNNING} {label}[/dim]"
        if state == "reviewing":
            return f"[bold #3d6b72]{_RUNNING} {label}[/bold #3d6b72]"
        dot_color = "#d97b6c" if self._error else "#7fc090"
        return f"[{dot_color}]{_DONE}[/{dot_color}] {label}"

    def _body_renderable(self) -> RenderableType:
        state = self._state
        if state == "running":
            return ""
        if state == "reviewing":
            return _render_diff(self._diff)
        prefix = "[#d97b6c]└ Error:[/#d97b6c]" if self._error else "[dim]└[/dim]"
        return f"{prefix} {self._summary}"

    def _hint_markup(self) -> str:
        if self._state == "reviewing":
            return (
                "  [bold #7fc090][[a]] apply[/bold #7fc090]"
                " [#585858]·[/#585858] "
                "[bold #d97b6c][[r]] reject[/bold #d97b6c]"
                " [#585858]·[/#585858] "
                "[bold #d4a050][[g]] regen[/bold #d4a050]"
            )
        return ""

    def _refresh_all(self) -> None:
        self.query_one("#card-header", Static).update(self._header_line())
        self.query_one("#card-body", Static).update(self._body_renderable())
        self.query_one("#card-hint", Static).update(self._hint_markup())

    # ── actions ───────────────────────────────────────────────────────────────

    def action_apply(self) -> None:
        if self._state == "reviewing":
            self.post_message(PatchDecision("apply"))

    def action_reject(self) -> None:
        if self._state == "reviewing":
            self.post_message(PatchDecision("reject"))

    def action_regen(self) -> None:
        if self._state == "reviewing":
            self.post_message(PatchDecision("regen"))

    # ── focus visibility ──────────────────────────────────────────────────────

    def on_focus(self) -> None:
        self.add_class("--focused")

    def on_blur(self) -> None:
        self.remove_class("--focused")
