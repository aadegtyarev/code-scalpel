"""Full-result viewer for a tool call (plan §v0.3 hook).

Inline ToolUseCard shows only the first ~5 lines of a result — render a
200-line `read_file` body there and Textual chokes. Ctrl+O on the chat
screen opens this modal with the full content, syntax-highlighted when
possible, scrollable. Escape closes.
"""

from __future__ import annotations

from rich.console import RenderableType
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
            f"{self._result.call.name}([dim]{args}[/dim])  "
            f"[dim]· {status} · {line_count} lines · {char_count} chars[/dim]"
        )

    def _body_renderable(self) -> RenderableType:
        out = self._result.output or "[dim](empty output)[/dim]"
        if not self._result.ok:
            # Errors are short, no point syntax-highlighting them.
            return out
        lexer = _infer_lexer_for(self._result.call)
        if lexer:
            return Syntax(
                out, lexer, theme="monokai", background_color="default", line_numbers=False
            )
        return out

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self._header_text(), id="trm-header")
            with VerticalScroll():
                yield Static(self._body_renderable(), id="trm-body")
            yield Static("[esc] close · [q] close", id="trm-hint")
