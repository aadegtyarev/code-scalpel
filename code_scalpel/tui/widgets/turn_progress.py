"""In-chat live progress line for an in-flight model turn.

Replaces the old `streaming · N tok/s` footer overload. While the model
streams, this widget sits inline in the chat at the same depth as the
upcoming reply and updates ~every 250 ms with elapsed time, token count,
streaming rate, and tool-call count.

When the turn finishes the caller removes this widget and prints the
permanent turn-summary line via `OutputLog.print_turn_summary(...)` —
two distinct concerns, two distinct widgets.

Why a dedicated class instead of inlining a Static: the formatting logic
(label, elapsed, tokens, rate, tools) is non-trivial and benefits from
unit testing in isolation. Keeping it here also keeps `OutputLog` thin.
"""

from __future__ import annotations

from textual.widgets import Static


def _format_progress(
    *,
    tokens: int,
    tool_calls: int,
    elapsed_s: float,
    rate_tok_s: float,
) -> str:
    """One-line progress text. Fields drop out when zero so the line
    starts compact (just elapsed) and grows as data arrives — mirrors
    how the user perceives a turn warming up."""
    parts: list[str] = ["thinking"]
    if elapsed_s > 0:
        parts.append(f"{elapsed_s:.0f}s")
    if tokens > 0:
        parts.append(f"↓ {tokens} tokens")
    if rate_tok_s > 0:
        parts.append(f"{rate_tok_s:.0f} tok/s")
    if tool_calls > 0:
        noun = "tool" if tool_calls == 1 else "tools"
        parts.append(f"🔧 {tool_calls} {noun}")
    return "⋯ " + " · ".join(parts)


class TurnProgress(Static):
    """Live inline progress widget. Plain `Static` — no markup parsing
    so an emoji or stray bracket can't blow up Rich. Styling comes from
    the `msg-turn-progress` CSS class on `OutputLog`."""

    def __init__(self) -> None:
        super().__init__("⋯ thinking", classes="msg-turn-progress", markup=False)
        self._tokens = 0
        self._tool_calls = 0
        self._elapsed_s = 0.0
        self._rate_tok_s = 0.0

    def update_progress(
        self,
        *,
        tokens: int | None = None,
        tool_calls: int | None = None,
        elapsed_s: float | None = None,
        rate_tok_s: float | None = None,
    ) -> None:
        """Partial-update friendly: any field left None keeps its previous
        value. The render call is cheap (Static.update); callers should
        still throttle to ~250 ms to avoid log-jamming the renderer."""
        if tokens is not None:
            self._tokens = tokens
        if tool_calls is not None:
            self._tool_calls = tool_calls
        if elapsed_s is not None:
            self._elapsed_s = elapsed_s
        if rate_tok_s is not None:
            self._rate_tok_s = rate_tok_s
        self.update(
            _format_progress(
                tokens=self._tokens,
                tool_calls=self._tool_calls,
                elapsed_s=self._elapsed_s,
                rate_tok_s=self._rate_tok_s,
            )
        )
