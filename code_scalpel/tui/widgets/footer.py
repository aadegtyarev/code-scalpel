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
    status: reactive[str] = reactive("")
    hints: reactive[str] = reactive("[tab] mode · [q] quit")
    model: reactive[str] = reactive("")
    # "4k/16k (26%)" — pre-formatted so the footer doesn't need to know
    # about Session/state internals. Empty string hides the segment.
    ctx: reactive[str] = reactive("")
    # Trust level indicator — short form ("skp" / "opt" / "ylo").
    # Always shown so the user knows the current safety level.
    trust: reactive[str] = reactive("")
    # Thinking effort indicator — shown only when model supports thinking
    # and effort is not "off". E.g. "◐ low", "◐ med", "◐ high".
    thinking: reactive[str] = reactive("")
    # Retry loop indicator — shown when iterative_patch_loop is active.
    loop: reactive[str] = reactive("")
    # LM Studio runtime state (`gen` / `idle`) — visible signal so user
    # can tell at a glance "model is still generating" vs "stuck on my
    # side". Set by App's poller (every ~1.5s via `lms ps`). Empty
    # string hides — for non-LM-Studio providers we have no busy info,
    # showing fake "idle" would be a lie.
    lm_state: reactive[str] = reactive("")

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

    def watch_trust(self, _: str) -> None:
        self._refresh_label()

    def watch_thinking(self, _: str) -> None:
        self._refresh_label()

    def watch_loop(self, _: str) -> None:
        self._refresh_label()

    def watch_lm_state(self, _: str) -> None:
        self._refresh_label()

    def _refresh_label(self) -> None:
        parts = [self.hints]
        if self.status:
            parts.append(self.status)
        indicators: list[str] = []
        if self.trust:
            # Escape [ so Rich doesn't swallow [skp]/[opt]/[ylo] as markup tags.
            indicators.append(self.trust.replace("[", r"\["))
        if self.thinking:
            indicators.append(self.thinking)
        if self.loop:
            indicators.append(self.loop)
        if self.lm_state:
            # Highlight only the active-generation state — idle is the
            # boring default, but `gen` is what the user wants to spot
            # at a glance.
            if self.lm_state == "gen":
                indicators.append("[yellow]● gen[/yellow]")
            elif self.lm_state == "idle":
                indicators.append("[dim]○ idle[/dim]")
            else:
                indicators.append(self.lm_state)
        if indicators:
            parts.append(" ".join(indicators))
        if self.ctx:
            parts.append(f"ctx {self.ctx}")
        if self.model:
            parts.append(f"[dim]{self.model}[/dim]")
        text = " · ".join(parts)
        with contextlib.suppress(Exception):
            self.query_one("#footer-label", Label).update(text)
