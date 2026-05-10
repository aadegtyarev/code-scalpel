"""Inline card for a model-initiated tool call (read_file / grep / run_tests).

One-line header by default; click the chevron to expand and see the body.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Collapsible, Static

from code_scalpel.tools.agent_tools import ToolCall, ToolResult


class ToolUseCard(Widget):
    DEFAULT_CSS = """
    ToolUseCard {
        height: auto;
        background: #0f0f0f;
        margin: 1 0 0 0;
        padding: 0;
    }
    ToolUseCard Collapsible {
        background: #0f0f0f;
        border: none;
        padding: 0;
        margin: 0;
    }
    ToolUseCard Collapsible > Contents {
        background: #161616;
        padding: 0 1;
        color: #a0a0a0;
    }
    ToolUseCard CollapsibleTitle {
        background: #0f0f0f;
        padding: 0;
        color: #a0a0a0;
    }
    ToolUseCard Static.body {
        height: auto;
        background: #161616;
        color: #a0a0a0;
    }
    """

    def __init__(self, call: ToolCall, result: ToolResult) -> None:
        super().__init__()
        self._call = call
        self._result = result

    def _title(self) -> str:
        dot = "[#5fbf5f]●[/]" if self._result.ok else "[#bf6060]●[/]"
        # arguments — compact, single-line
        args = self._call.body.replace("\n", " ").strip()
        if len(args) > 60:
            args = args[:57] + "…"
        summary = self._summarize_output()
        return f"{dot} [bold]{self._call.name}[/bold]([dim]{args}[/dim]) [dim]· {summary}[/dim]"

    def _summarize_output(self) -> str:
        out = self._result.output
        if not self._result.ok:
            first = out.split("\n", 1)[0]
            return f"failed: {first[:80]}"
        # heuristics per tool
        if self._call.name == "read_file":
            n = out.count("\n")
            return f"{n} lines"
        if self._call.name == "grep":
            if out.startswith("no matches"):
                return "no matches"
            return f"{out.count(chr(10)) + 1} matches"
        if self._call.name == "run_tests":
            first = out.split("\n", 1)[0]
            return first[:80]
        return f"{len(out)} chars"

    def compose(self) -> ComposeResult:
        with Collapsible(title=self._title(), collapsed=True):
            yield Static(self._result.output, classes="body")
