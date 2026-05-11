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
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from code_scalpel.tools.agent_tools import ToolResult
from code_scalpel.tui.widgets._map_highlight import highlight_map
from code_scalpel.tui.widgets.tool_use import _infer_lexer_for


class ToolResultModal(ModalScreen[None]):
    """Modal that shows the full output of one tool call."""

    DEFAULT_CSS = """
    ToolResultModal {
        align: center middle;
    }
    ToolResultModal > Vertical {
        background: #161616;
        border: round #3a3a3a;
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
        color: #585858;
        padding: 1 0 0 0;
    }
    ToolResultModal VerticalScroll {
        height: 1fr;
        background: #0f0f0f;
        border: round #2a2a2a;
        padding: 0 1;
        scrollbar-size-vertical: 1;
        scrollbar-color: #2a2a2a;
        scrollbar-color-hover: #404040;
        scrollbar-color-active: #5fbf5f;
        scrollbar-background: #0f0f0f;
        scrollbar-background-hover: #0f0f0f;
        scrollbar-background-active: #0f0f0f;
    }
    ToolResultModal #trm-body {
        height: auto;
        background: #0f0f0f;
        color: #c0c0c0;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("ctrl+o", "dismiss", "Close", show=False),
        Binding("ctrl+c", "copy", "Copy"),
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
        """Highlighted body for successful read_file or project_map; None for
        everything else (compose() will render plain text with markup=False).
        """
        if not self._result.output or not self._result.ok:
            return None
        # Custom highlight for project_map — the format isn't valid Python,
        # so no Pygments lexer fits. See _map_highlight.py. Line numbers
        # are prepended manually because rich.Text has no built-in gutter.
        if self._result.call.name == "project_map":
            return _prepend_line_numbers(highlight_map(self._result.output))
        lexer = _infer_lexer_for(self._result.call)
        if lexer:
            return Syntax(
                self._result.output,
                lexer,
                theme="monokai",
                background_color="default",
                line_numbers=True,
                word_wrap=True,
            )
        return None

    @staticmethod
    def _with_line_numbers(text: str) -> str:
        """Prepend 1-indexed line numbers to plain-text bodies (grep
        results, run_tests output). Right-aligned to the widest line-number
        width so the gutter stays straight."""
        lines = text.splitlines() or [""]
        width = len(str(len(lines)))
        return "\n".join(f"{i:>{width}}  {line}" for i, line in enumerate(lines, 1))


def _prepend_line_numbers(text: Text) -> Text:
    """Same idea as _with_line_numbers but for an already-styled rich.Text.
    Splits on newlines (preserving spans), prepends a dim gutter, and
    reassembles. The gutter style matches the modal's secondary colour."""
    lines = text.split("\n", allow_blank=True)
    width = len(str(len(lines)))
    out = Text()
    for i, line in enumerate(lines, 1):
        out.append(f"{i:>{width}}  ", style="dim #707070")
        out.append_text(line)
        if i < len(lines):
            out.append("\n")
    return out

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self._header_text(), id="trm-header")
            with VerticalScroll():
                highlighted = self._body_renderable()
                if highlighted is not None:
                    # Syntax handles its own line numbers + wrap.
                    yield Static(highlighted, id="trm-body")
                elif not self._result.output:
                    yield Static("[dim](empty output)[/dim]", id="trm-body")
                else:
                    # Plain text: prepend our own line numbers, mark up off.
                    yield Static(
                        self._with_line_numbers(self._result.output),
                        id="trm-body",
                        markup=False,
                    )
            yield Static(r"\[esc] close · \[ctrl+c] copy", id="trm-hint")

    def action_copy(self) -> None:
        """Ctrl+C copies the raw tool output (not the rendered highlight).
        Surfaces a passive toast so the user knows it landed — no action
        required to dismiss."""
        text = self._result.output or ""
        try:
            self.app.copy_to_clipboard(text)
        except Exception:
            # Some terminals don't support OSC52 — let the user know.
            self.app.notify(
                "Clipboard not supported by this terminal.",
                title="Copy",
                severity="warning",
                timeout=2,
            )
            return
        self.app.notify(
            f"Copied {len(text)} chars to clipboard.",
            title="Copy",
            timeout=2,
        )
