from __future__ import annotations

import contextlib

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label


class StatusFooter(Widget):
    DEFAULT_CSS = """
    StatusFooter {
        height: 1;
        background: #1c1c1c;
        color: #a0a0a0;
        padding: 0 1;
    }
    """

    # Footer carries current state, key hints, model, and a context bar.
    # Per-turn metrics (tools, tokens, speed) stay inline in the chat as
    # a turn-summary line. Ctx is in the footer because it's continuous
    # state — every keystroke moves you toward the limit, not just turns.
    status: reactive[str] = reactive("● idle")
    hints: reactive[str] = reactive("[tab] mode · [q] quit")
    model: reactive[str] = reactive("")
    # "4k/16k (26%)" — pre-formatted so the footer doesn't need to know
    # about Session/state internals. Empty string hides the segment.
    ctx: reactive[str] = reactive("")

    def compose(self) -> ComposeResult:
        yield Label("", id="footer-label")

    def on_mount(self) -> None:
        self._refresh_label()

    def watch_status(self, _: str) -> None:
        self._refresh_label()

    def watch_hints(self, _: str) -> None:
        self._refresh_label()

    def watch_model(self, _: str) -> None:
        self._refresh_label()

    def watch_ctx(self, _: str) -> None:
        self._refresh_label()

    def _refresh_label(self) -> None:
        parts = [self.hints, self.status]
        if self.ctx:
            parts.append(f"ctx {self.ctx}")
        if self.model:
            parts.append(f"[dim]{self.model}[/dim]")
        text = " · ".join(parts)
        with contextlib.suppress(Exception):
            self.query_one("#footer-label", Label).update(text)
