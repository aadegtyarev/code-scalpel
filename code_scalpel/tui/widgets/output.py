from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import Markdown, Static


class OutputLog(VerticalScroll):
    """Output stream: messages mount at bottom and grow upward as more are added."""

    DEFAULT_CSS = """
    OutputLog {
        height: 1fr;
        background: #0f0f0f;
        border: none;
        padding: 0 1;
        scrollbar-color: #3a3a3a;
        scrollbar-background: #0f0f0f;
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
    OutputLog Static.msg-error {
        height: auto;
        margin: 1 0 0 0;
        color: #ff5555;
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
        self.run_worker(self._append(Static(text, classes="msg-user")), exclusive=False)

    def print_assistant(self, text: str) -> Markdown:
        widget = Markdown(text)
        self.run_worker(self._append(widget), exclusive=False)
        return widget

    def print_status(self, text: str) -> None:
        self.run_worker(self._append(Static(text, classes="msg-status")), exclusive=False)

    def print_error(self, text: str) -> None:
        self.run_worker(self._append(Static(text, classes="msg-error")), exclusive=False)
