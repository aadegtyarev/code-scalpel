from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import Markdown, Static

from code_scalpel.tools.agent_tools import ToolCall, ToolResult
from code_scalpel.tui.widgets.tool_use import ToolUseCard
from code_scalpel.tui.widgets.turn_progress import TurnProgress


class OutputLog(VerticalScroll):
    """Output stream: messages mount at bottom and grow upward as more are added."""

    DEFAULT_CSS = """
    OutputLog {
        height: 1fr;
        background: #0f0f0f;
        border: none;
        padding: 0 1;
        scrollbar-size-vertical: 1;
        scrollbar-color: #2a2a2a;
        scrollbar-color-hover: #404040;
        scrollbar-color-active: #505050;
        scrollbar-background: #0f0f0f;
        scrollbar-background-hover: #0f0f0f;
        scrollbar-background-active: #0f0f0f;
    }
    OutputLog > #_spacer {
        height: 1fr;
        min-height: 0;
    }
    OutputLog Static.msg-user {
        height: auto;
        margin: 1 0 0 0;
        color: #d0d0d0;
        text-style: bold;
        background: #0f0f0f;
    }
    OutputLog Static.msg-status {
        height: auto;
        margin: 1 0 0 0;
        color: #585858;
        background: #0f0f0f;
    }
    OutputLog Static.msg-summary {
        /* Post-turn summary line — same brightness as the footer
           (#a0a0a0) so it's legible without competing with chat text. */
        height: auto;
        margin: 1 0 0 0;
        color: #a0a0a0;
        background: #0f0f0f;
    }
    OutputLog Static.msg-turn-progress {
        /* In-flight turn progress — slightly dimmer than the final
           summary so the eye reads it as "ephemeral, still working". */
        height: 1;
        margin: 1 0 0 0;
        color: #808080;
        background: #0f0f0f;
    }
    OutputLog Static.msg-error {
        height: auto;
        margin: 1 0 0 0;
        color: #bf6060;
        background: #0f0f0f;
    }
    OutputLog Static.msg-stream {
        height: auto;
        margin: 1 0 0 0;
        color: #808080;
        background: #0f0f0f;
    }
    OutputLog Markdown {
        height: auto;
        margin: 1 0 0 0;
        padding: 0;
        background: #0f0f0f;
    }
    OutputLog Markdown MarkdownFence,
    OutputLog Markdown MarkdownBlock {
        background: #0f0f0f;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("", id="_spacer")

    async def _append(self, widget: Widget) -> None:
        await self.mount(widget)
        self.call_after_refresh(self.scroll_end, animate=False)

    def print_user(self, text: str) -> None:
        # User input may contain `[...]` (e.g. a literal bracketed phrase) —
        # markup=False so Rich doesn't try to parse it as a tag.
        self.run_worker(
            self._append(Static(text, classes="msg-user", markup=False)),
            exclusive=False,
        )

    def print_assistant(self, text: str) -> Markdown:
        widget = Markdown(text)
        self.run_worker(self._append(widget), exclusive=False)
        return widget

    def start_turn_progress(self) -> TurnProgress:
        """Mount the live in-chat progress widget for an in-flight turn.
        Returned so the caller can `update_progress(...)` it on each
        stream tick and `remove()` it once the turn finalises."""
        p = TurnProgress()
        self.run_worker(self._append(p), exclusive=False)
        return p

    def start_streaming(self) -> Static:
        """A fast Static widget for stream-in-progress text. Use this during the
        stream, then call finalize_streaming() to swap to a Markdown widget."""
        s = Static("", classes="msg-stream", markup=False)
        self.run_worker(self._append(s), exclusive=False)
        return s

    async def finalize_streaming(self, placeholder: Static, final_text: str) -> Markdown:
        """Replace the live Static with a rendered Markdown widget."""
        md = Markdown(final_text)
        try:
            await self.mount(md, after=placeholder)
            await placeholder.remove()
        except Exception:
            pass
        self.call_after_refresh(self.scroll_end, animate=False)
        return md

    def print_status(self, text: str, *, markup: bool = True) -> None:
        """Mount a status line. markup=False for raw text that contains
        brackets / Python code (project map dumps, file paths) which would
        otherwise blow up Rich's markup parser."""
        self.run_worker(
            self._append(Static(text, classes="msg-status", markup=markup)),
            exclusive=False,
        )

    def print_turn_summary(self, text: str) -> None:
        """Inline per-turn summary (tools, tokens, speed, ctx). Brighter
        than the regular status line so it's readable alongside chat text."""
        self.run_worker(
            self._append(Static(text, classes="msg-summary")),
            exclusive=False,
        )

    def print_error(self, text: str, *, markup: bool = True) -> None:
        self.run_worker(
            self._append(Static(text, classes="msg-error", markup=markup)),
            exclusive=False,
        )

    def add_tool_use(self, call: ToolCall, result: ToolResult) -> None:
        self.run_worker(self._append(ToolUseCard(call, result)), exclusive=False)
