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

    # Footer is intentionally minimal — just current state, key hints, and
    # the active model. Per-turn metrics (tools, tokens, speed, ctx) are
    # printed inline in the chat as a turn-summary line, Claude-Code style.
    status: reactive[str] = reactive("● idle")
    hints: reactive[str] = reactive("[tab] mode · [q] quit")
    model: reactive[str] = reactive("")

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

    def _refresh_label(self) -> None:
        parts = [self.hints, self.status]
        if self.model:
            parts.append(f"[dim]{self.model}[/dim]")
        text = " · ".join(parts)
        with contextlib.suppress(Exception):
            self.query_one("#footer-label", Label).update(text)
