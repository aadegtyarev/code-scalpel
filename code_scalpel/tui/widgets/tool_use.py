"""Inline card for a model-initiated tool call (read_file / grep / run_tests).

One-line header by default; click the chevron to expand and see the body.
"""

from __future__ import annotations

import json

from rich.console import RenderableType
from rich.syntax import Syntax
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Collapsible, Static

from code_scalpel.tools.agent_tools import ToolCall, ToolResult

# Filename extension → Pygments lexer name. Restricted to languages we
# actually expect to see in a project context; unknown extensions fall back
# to plain text so the preview at least stays readable.
_LEXER_BY_EXT: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".jsx": "jsx",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".kt": "kotlin",
    ".rb": "ruby",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".json": "json",
    ".md": "markdown",
    ".sql": "sql",
    ".html": "html",
    ".css": "css",
    ".tcss": "css",
    ".xml": "xml",
}


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

    _PREVIEW_LINES = 5

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
            # splitlines drops the trailing newline ripgrep usually emits — so
            # "a\nb\nc\n" reports 3 matches, not 4. Non-empty filter guards
            # against accidental double newlines in the output.
            return f"{sum(1 for ln in out.splitlines() if ln)} matches"
        if self._call.name == "run_tests":
            first = out.split("\n", 1)[0]
            return first[:80]
        return f"{len(out)} chars"

    def _preview_text(self) -> tuple[str, int]:
        """Return (head, hidden_count). head is the first N lines; hidden_count
        is the number of trailing lines elided."""
        out = self._result.output
        lines = out.splitlines()
        if len(lines) <= self._PREVIEW_LINES:
            return out, 0
        head = "\n".join(lines[: self._PREVIEW_LINES])
        return head, len(lines) - self._PREVIEW_LINES

    def _preview_renderable(self) -> RenderableType:
        """Build the body renderable. For successful read_file calls we
        syntax-highlight the preview based on the file extension; everything
        else stays plain (avoids dragging Pygments into shell/grep output)."""
        head, hidden = self._preview_text()
        lexer = self._infer_lexer()
        if lexer and self._result.ok:
            return Syntax(head, lexer, theme="monokai", background_color="default")
        if hidden:
            return f"{head}\n[dim]… {hidden} more lines (Ctrl+O for full view)[/]"
        return head

    def _infer_lexer(self) -> str | None:
        """Look up a Pygments lexer for read_file output via the path
        argument. Other tools return None — keep their output as plain text."""
        if self._call.name != "read_file":
            return None
        try:
            args = json.loads(self._call.body)
        except (json.JSONDecodeError, TypeError):
            return None
        path = args.get("path") if isinstance(args, dict) else None
        if not isinstance(path, str):
            return None
        dot = path.rfind(".")
        if dot == -1:
            return None
        return _LEXER_BY_EXT.get(path[dot:].lower())

    def compose(self) -> ComposeResult:
        with Collapsible(title=self._title(), collapsed=True):
            renderable = self._preview_renderable()
            head, hidden = self._preview_text()
            # When the renderable is a Syntax object the truncation hint
            # doesn't live inside it — emit it as a separate dim line so the
            # user still sees "more lines" without polluting the highlight.
            yield Static(renderable, classes="body")
            if hidden and isinstance(renderable, Syntax):
                yield Static(
                    f"[dim]… {hidden} more lines (Ctrl+O for full view)[/]",
                    classes="body",
                )
