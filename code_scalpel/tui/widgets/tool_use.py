"""Inline card for a model-initiated tool call (read_file / grep / run_tests).

One-line header by default; click the chevron to expand and see the body.
"""

from __future__ import annotations

import json

from rich.console import RenderableType
from rich.markup import escape
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


def _infer_lexer_for(call: ToolCall) -> str | None:
    """Pygments lexer name for a tool call's output, if known. Currently
    only `read_file` is highlightable — we derive the lexer from the
    `path` argument's extension. Returns None for everything else so the
    caller falls back to plain text."""
    if call.name != "read_file":
        return None
    try:
        args = json.loads(call.body)
    except (json.JSONDecodeError, TypeError):
        return None
    path = args.get("path") if isinstance(args, dict) else None
    if not isinstance(path, str):
        return None
    dot = path.rfind(".")
    if dot == -1:
        return None
    return _LEXER_BY_EXT.get(path[dot:].lower())


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

    def __init__(
        self,
        call: ToolCall,
        result: ToolResult,
        *,
        full: bool = False,
    ) -> None:
        """`full=True` skips the preview-truncation: the card renders the
        whole `result.output` inline. Use it for tool cards whose body is
        intentionally short (e.g. /stats — 6-10 rows of session metadata)
        where the "… N more lines (Ctrl+O for full view)" footer just
        wastes a slot and forces a modal for nothing."""
        super().__init__()
        self._call = call
        self._result = result
        self._full = full

    def _title(self) -> str:
        dot = "[#5fbf5f]●[/]" if self._result.ok else "[#bf6060]●[/]"
        # arguments — compact, single-line; escaped because tool args
        # often contain brackets/quotes that Rich's markup parser eats.
        args = self._call.body.replace("\n", " ").strip()
        if len(args) > 60:
            args = args[:57] + "…"
        summary = self._summarize_output()
        return (
            f"{dot} [bold]{self._call.name}[/bold]"
            f"([dim]{escape(args)}[/dim]) [dim]· {escape(summary)}[/dim]"
        )

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
        # Default for any other tool name (incl. synthetic ones like
        # `project_map`): lines first, then char count for empty/short.
        n_lines = out.count("\n") + 1 if out else 0
        if n_lines > 1:
            return f"{n_lines} lines"
        return f"{len(out)} chars"

    def _preview_text(self) -> tuple[str, int]:
        """Return (head, hidden_count). head is the first N lines; hidden_count
        is the number of trailing lines elided. `full=True` short-circuits
        the cap so the whole output renders inline."""
        out = self._result.output
        if self._full:
            return out, 0
        lines = out.splitlines()
        if len(lines) <= self._PREVIEW_LINES:
            return out, 0
        head = "\n".join(lines[: self._PREVIEW_LINES])
        return head, len(lines) - self._PREVIEW_LINES

    def _preview_renderable(self) -> RenderableType | None:
        """Body renderable for the preview. For successful read_file calls
        we syntax-highlight via Rich's Syntax (its own renderer, markup
        irrelevant). Everything else returns None — the compose() path then
        renders raw text in a Static with markup=False, which is the proper
        way to display file/grep output without Rich parsing brackets."""
        head, _hidden = self._preview_text()
        lexer = self._infer_lexer()
        if lexer and self._result.ok:
            return Syntax(head, lexer, theme="monokai", background_color="default")
        return None

    def _infer_lexer(self) -> str | None:
        return _infer_lexer_for(self._call)

    def compose(self) -> ComposeResult:
        with Collapsible(title=self._title(), collapsed=True):
            highlighted = self._preview_renderable()
            head, hidden = self._preview_text()
            if highlighted is not None:
                yield Static(highlighted, classes="body")
            else:
                # Plain branch: markup=False so brackets/equals in file
                # bodies or grep matches don't blow up Rich's parser.
                yield Static(head, classes="body", markup=False)
            if hidden:
                yield Static(
                    f"[dim]… {hidden} more lines (Ctrl+O for full view)[/]",
                    classes="body",
                )

    def on_mount(self) -> None:
        # CollapsibleTitle is focusable by default, which means every
        # history tool card lands a Tab stop. The user complaint: Tab from
        # the input pages through past tool cards before reaching anything
        # actionable. Strip the title (and any child widget — read-only
        # bodies don't need keyboard focus either) out of the Tab cycle.
        # Programmatic focus via Ctrl+↑/↓ still works — see focus_card().
        from textual.widgets._collapsible import CollapsibleTitle

        for title in self.query(CollapsibleTitle):
            title.can_focus = False

    def focus_card(self) -> None:
        """Programmatically focus this card's CollapsibleTitle.

        on_mount() turns can_focus off so Tab skips us; this method
        temporarily flips it back on, focuses the title, and scrolls it
        into view. The Tab cycle stays clean — only Ctrl+↑/↓ in
        ScalpelApp can land here.

        Enter/Space on the focused title fire Collapsible's built-in
        toggle action; the user gets fold/unfold for free.
        """
        from textual.widgets._collapsible import CollapsibleTitle

        try:
            title = self.query_one(CollapsibleTitle)
        except Exception:
            return
        title.can_focus = True
        title.focus()
        self.scroll_visible(animate=False)
