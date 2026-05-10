from __future__ import annotations

from typing import Literal

from textual.app import ComposeResult
from textual.binding import Binding
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

_RUNNING = "◌"
_DONE = "●"


def _colorize_diff(diff: str) -> str:
    """Return Rich markup for a unified diff string."""
    lines: list[str] = []
    for line in diff.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            lines.append(f"[dim]{line}[/dim]")
        elif line.startswith("+"):
            lines.append(f"[#9fc99f]{line}[/#9fc99f]")
        elif line.startswith("-"):
            lines.append(f"[#bf6060]{line}[/#bf6060]")
        elif line.startswith("@@"):
            lines.append(f"[#3a3a3a]{line}[/#3a3a3a]")
        else:
            lines.append(line)
    return "\n".join(lines)


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
        dot_color = "#bf6060" if self._error else "#7fb87f"
        return f"[{dot_color}]{_DONE}[/{dot_color}] {label}"

    def _body_markup(self) -> str:
        state = self._state
        if state == "running":
            return ""
        if state == "reviewing":
            return _colorize_diff(self._diff)
        prefix = "[#bf6060]└ Error:[/#bf6060]" if self._error else "[dim]└[/dim]"
        return f"{prefix} {self._summary}"

    def _hint_markup(self) -> str:
        if self._state == "reviewing":
            return (
                "  [bold #7fb87f][[a]] apply[/bold #7fb87f]"
                " [#585858]·[/#585858] "
                "[bold #bf6060][[r]] reject[/bold #bf6060]"
                " [#585858]·[/#585858] "
                "[bold #d4a070][[g]] regen[/bold #d4a070]"
            )
        return ""

    def _refresh_all(self) -> None:
        self.query_one("#card-header", Static).update(self._header_line())
        self.query_one("#card-body", Static).update(self._body_markup())
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
