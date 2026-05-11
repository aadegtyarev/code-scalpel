"""Full-result viewer for a tool call (plan §v0.3 hook).

Inline ToolUseCard shows only the first ~5 lines of a result — render a
200-line `read_file` body there and Textual chokes. Ctrl+O on the chat
screen opens this modal with the full content, syntax-highlighted when
possible, scrollable. Escape closes.
"""

from __future__ import annotations

from rich.console import RenderableType
from rich.markup import escape
from rich.syntax import Syntax
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from code_scalpel.tools.agent_tools import ToolResult
from code_scalpel.tui.widgets.tool_use import _infer_lexer_for


class ToolResultModal(ModalScreen[None]):
    """Modal that shows the full output of one tool call."""

    DEFAULT_CSS = """
    ToolResultModal {
        align: center middle;
    }
    ToolResultModal > Vertical {
        background: #161616;
        border: round #444444;
        width: 90%;
        height: 90%;
        padding: 1 2;
    }
    ToolResultModal #trm-header {
        height: auto;
        color: #d0d0d0;
        text-style: bold;
        padding: 0 0 1 0;
    }
    ToolResultModal #trm-hint {
        height: auto;
        color: #707070;
        padding: 1 0 0 0;
    }
    ToolResultModal VerticalScroll {
        height: 1fr;
        background: #0f0f0f;
        border: tall #2a2a2a;
        padding: 0 1;
    }
    ToolResultModal #trm-body {
        height: auto;
        background: #0f0f0f;
        color: #d0d0d0;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("ctrl+o", "dismiss", "Close", show=False),
        Binding("q", "dismiss", "Close"),
    ]

    def __init__(self, result: ToolResult) -> None:
        super().__init__()
        self._result = result

    def _header_text(self) -> str:
        status = "[#5fbf5f]ok[/]" if self._result.ok else "[#bf6060]failed[/]"
        out = self._result.output
        line_count = len(out.splitlines()) if out else 0
        char_count = len(out)
        args = self._result.call.body.replace("\n", " ").strip()
        if len(args) > 80:
            args = args[:77] + "…"
        return (
            f"{self._result.call.name}([dim]{escape(args)}[/dim])  "
            f"[dim]· {status} · {line_count} lines · {char_count} chars[/dim]"
        )

    def _body_renderable(self) -> RenderableType | None:
        """Highlighted body for successful read_file; None for everything
        else (compose() will render plain text with markup=False)."""
        if not self._result.output or not self._result.ok:
            return None
        lexer = _infer_lexer_for(self._result.call)
        if lexer:
            return Syntax(
                self._result.output,
                lexer,
                theme="monokai",
                background_color="default",
                line_numbers=False,
            )
        return None

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self._header_text(), id="trm-header")
            with VerticalScroll():
                highlighted = self._body_renderable()
                if highlighted is not None:
                    yield Static(highlighted, id="trm-body")
                elif not self._result.output:
                    yield Static("[dim](empty output)[/dim]", id="trm-body")
                else:
                    # Plain text branch: markup=False so file contents
                    # / traceback brackets don't blow up Rich.
                    yield Static(self._result.output, id="trm-body", markup=False)
            # `\[` escapes the literal bracket in Rich markup so `[esc]` /
            # `[q]` aren't parsed as opening tags.
            yield Static(r"\[esc] close · \[q] close", id="trm-hint")
