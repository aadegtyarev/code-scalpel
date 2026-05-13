"""OperationCard — unified phase + timer + progress widget.

The chat used to have two visually distinct UIs for «something is
happening»: TurnProgress (single spinner line that disappears) and
the various tool cards. For operations that go through several
phases — model load, prompt processing, generation, post-pass —
neither is honest. The user sees «◌ thinking… [23s]» and doesn't
know if it's loading the model, parsing the prompt, or actually
generating.

OperationCard models the operation as a typed phase list and a
timer. Two data sources:

- **Native (LM Studio `/api/v1/chat`)**: real events drive the
  phase transitions and the progress bars (model_load.progress,
  prompt_processing.progress are 0..1 floats from the server).
- **Fallback (OpenAI-compat `/v1/chat/completions`)**: caller
  walks the phases manually (`begin(phase)` / `update_progress(p)`
  / `set_phase(next)`). Loading-vs-processing is inferred by
  probing `/api/v1/models` for `loaded_instances` of the target
  model; if cold, we mount with phase=loading.

Either way the user sees the same layout — that was the design
constraint the user set: «единообразние интерфейса, не важно
как под капотом».

The card stays in the chat as a след after completion: final
phase shows ✓ and the full timeline is browsable in history.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import Static

# Phase identifiers. Order matters — UI displays phases that have
# fired (current state ≥ phase index) with their final marker; the
# active phase shows a spinner; not-yet-started phases are hidden.
Phase = Literal[
    "loading",  # model_load.start..end (or cold-load fallback)
    "processing",  # prompt_processing.start..end (or pre-first-chunk wait)
    "generating",  # message.delta arriving
    "done",  # chat.end (or finalizer)
    "error",  # error event or HTTP failure
]

_PHASE_ORDER: tuple[Phase, ...] = ("loading", "processing", "generating", "done")
_PHASE_EMOJI: dict[Phase, str] = {
    "loading": "🔄",
    "processing": "📊",
    "generating": "💬",
    "done": "✓",
    "error": "✗",
}
_PHASE_LABEL: dict[Phase, str] = {
    "loading": "Loading",
    "processing": "Processing prompt",
    "generating": "Generating",
    "done": "Done",
    "error": "Error",
}


@dataclass
class PhaseRecord:
    """One phase's lifetime + optional progress.

    `started_at` and `ended_at` are wall-clock seconds since the
    operation began (so a phase that ran from 5s to 12s reads
    «[12s]» in the UI, not the absolute timestamp). `progress` is
    a 0..1 float when the data source provides one (native
    events do; fallback usually doesn't and renders «(cold)» or
    nothing).
    """

    started_at: float
    ended_at: float | None = None
    progress: float | None = None  # None = no progress bar, just a spinner
    detail: str = ""  # short text like "qwen-14b" or "8.2k tokens"


@dataclass
class OperationState:
    """Snapshot of where the operation is right now. Held as a
    reactive on the widget so changes auto-redraw."""

    title: str = "operation"
    started_at: float = field(default_factory=time.monotonic)
    current_phase: Phase | None = None
    phases: dict[Phase, PhaseRecord] = field(default_factory=dict)
    final_summary: str = ""  # populated on done() / fail()


def _format_progress_bar(progress: float, width: int = 10) -> str:
    """Compact unicode bar, no library. progress in [0..1].

    Empty cells are dim, filled cells bright. Width 10 fits the
    inline card without wrapping on terminals ≥80 cols even when
    a long detail line is present."""
    filled = max(0, min(width, int(round(progress * width))))
    return "▓" * filled + "░" * (width - filled)


def _format_seconds(seconds: float) -> str:
    """`[12.3s]` for short, `[1m 12s]` for long — matches the
    convention `Session.summary_line` uses in the footer so the
    user sees the same shape everywhere."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    mins, secs = divmod(int(seconds), 60)
    return f"{mins}m {secs}s"


class OperationCard(Widget):
    """Inline card that walks an operation through its phases with
    a live timer and (when available) a progress bar.

    Usage from the consumer side:

        card = OperationCard(title="upstream flush", id="card-N")
        await mount(card, before=input_widget)

        # Native path — feed events:
        async for event in native_chat(...):
            card.ingest(event)

        # Fallback path — drive phases manually:
        card.begin("loading", detail="qwen-14b cold")
        # ... cold-load wait ...
        card.set_phase("processing", detail="8.2k tokens")
        # ... wait for first chunk ...
        card.set_phase("generating")
        card.append_text("hello")
        # ...
        card.done("1042 out / 8200 in")

    `cancel()` is a hook for Esc — the caller decides what to
    actually abort (HTTP request, async task). The widget just
    marks the current phase as error and stops the timer.
    """

    DEFAULT_CSS = """
    OperationCard {
        height: auto;
        background: #0f0f0f;
        padding: 0 1;
        margin: 0;
    }
    OperationCard .dim {
        color: #585858;
    }
    """

    can_focus = True
    _state: reactive[OperationState] = reactive(OperationState(), recompose=False)

    def __init__(self, title: str, card_id: int = 0) -> None:
        super().__init__()
        self._card_id = card_id
        self._title = title
        self._tick_handle: Timer | None = None
        # Mutable state stored separately from reactive so we can
        # mutate fields in-place without triggering full recompose.
        # The watcher rebinds when we explicitly call _refresh().
        self._state = OperationState(title=title)

    @property
    def card_id(self) -> int:
        return self._card_id

    def compose(self) -> ComposeResult:
        yield Static("", id="card-body")

    def on_mount(self) -> None:
        # 5 Hz redraws are enough — humans don't perceive sub-200ms
        # latency in a status bar. Halts via `_stop_ticker` on done.
        self._tick_handle = self.set_interval(0.2, self._refresh)
        self._refresh()

    def _now(self) -> float:
        return time.monotonic() - self._state.started_at

    # ── public API ────────────────────────────────────────────────

    def begin(self, phase: Phase, *, detail: str = "") -> None:
        """Open `phase` if not already open. Idempotent — repeated
        calls are no-ops, which makes the native-events ingestion
        path simpler (server sometimes emits start events without
        a preceding end)."""
        if phase in self._state.phases:
            return
        self._state.phases[phase] = PhaseRecord(started_at=self._now(), detail=detail)
        self._state.current_phase = phase

    def set_progress(self, phase: Phase, progress: float) -> None:
        """Update the progress bar of `phase` — 0..1. If `phase`
        isn't open yet, we open it (server sometimes skips the
        start event)."""
        if phase not in self._state.phases:
            self.begin(phase)
        rec = self._state.phases[phase]
        rec.progress = max(0.0, min(1.0, progress))

    def end_phase(self, phase: Phase) -> None:
        """Close `phase`. Final time stamp captured; the UI
        switches from «active» to «completed» rendering."""
        rec = self._state.phases.get(phase)
        if rec is None or rec.ended_at is not None:
            return
        rec.ended_at = self._now()

    def set_phase(self, phase: Phase, *, detail: str = "") -> None:
        """Transition convenience: close current_phase, open new
        one. The most common pattern from the fallback path —
        «I'm done loading, now processing»."""
        if self._state.current_phase is not None:
            self.end_phase(self._state.current_phase)
        self.begin(phase, detail=detail)

    def append_text(self, content: str) -> None:
        """Streaming text delta — concatenated into the `generating`
        phase's detail. The fallback path uses this to show how
        much has been emitted; native MessageDelta routes here too."""
        if "generating" not in self._state.phases:
            self.begin("generating")
        rec = self._state.phases["generating"]
        rec.detail = (rec.detail + content)[-200:]  # keep the tail only

    def done(self, summary: str = "") -> None:
        """Mark the operation complete. Final phase is closed; the
        card stops ticking and stays as след."""
        if self._state.current_phase is not None:
            self.end_phase(self._state.current_phase)
        self._state.current_phase = "done"
        self._state.phases["done"] = PhaseRecord(
            started_at=self._now(),
            ended_at=self._now(),
        )
        self._state.final_summary = summary
        self._stop_ticker()
        self._refresh()

    def fail(self, error: str) -> None:
        """Like done(), but for failures. Renders ✗ marker and the
        error text remains in the card so the user sees why."""
        if (
            self._state.current_phase is not None
            and self._state.current_phase in self._state.phases
        ):
            self.end_phase(self._state.current_phase)
        self._state.current_phase = "error"
        self._state.phases["error"] = PhaseRecord(
            started_at=self._now(),
            ended_at=self._now(),
            detail=error,
        )
        self._state.final_summary = error
        self._stop_ticker()
        self._refresh()

    def cancel(self) -> None:
        """User pressed Esc / called Cancel. Marks error with a
        canonical message; the caller is responsible for actually
        aborting the underlying work."""
        self.fail("cancelled")

    def ingest(self, event: object) -> None:
        """Native-path entry point. Maps a NativeStreamEvent to the
        right phase mutation. Unknown events are silently dropped
        — same forgiveness policy as the SSE parser."""
        from code_scalpel.llm.native_events import (
            ChatEnd,
            ChatStart,
            MessageDelta,
            MessageEnd,
            MessageStart,
            ModelLoadEnd,
            ModelLoadProgress,
            ModelLoadStart,
            PromptProcessingEnd,
            PromptProcessingProgress,
            PromptProcessingStart,
            StreamError,
        )

        if isinstance(event, ChatStart):
            return  # nothing to render — operation already started on mount
        if isinstance(event, ModelLoadStart):
            self.begin("loading")
            return
        if isinstance(event, ModelLoadProgress):
            self.set_progress("loading", event.progress)
            return
        if isinstance(event, ModelLoadEnd):
            self.end_phase("loading")
            return
        if isinstance(event, PromptProcessingStart):
            self.set_phase("processing")
            return
        if isinstance(event, PromptProcessingProgress):
            self.set_progress("processing", event.progress)
            return
        if isinstance(event, PromptProcessingEnd):
            self.end_phase("processing")
            return
        if isinstance(event, MessageStart):
            self.set_phase("generating")
            return
        if isinstance(event, MessageDelta):
            self.append_text(event.content)
            return
        if isinstance(event, MessageEnd):
            self.end_phase("generating")
            return
        if isinstance(event, StreamError):
            self.fail(event.message)
            return
        if isinstance(event, ChatEnd):
            self.done(
                f"{event.completion_tokens} out / {event.prompt_tokens} in, "
                f"{_format_seconds(event.total_time_seconds)}"
            )
            return

    # ── rendering ────────────────────────────────────────────────

    def render_body(self) -> str:
        """Build the full body text. Each fired phase is one line:
        emoji  label[detail]  bar(if any)   [time]   ✓/spinner

        Lines for finished phases use a small ✓; the active phase
        shows a spinner (or no marker if no progress). Done line
        carries `final_summary` instead of a label."""
        lines: list[str] = [f"[bold #3d6b72]▶ {self._title}[/bold #3d6b72]"]
        total_elapsed = self._now()

        for phase in _PHASE_ORDER:
            if phase not in self._state.phases:
                continue
            rec = self._state.phases[phase]
            is_active = self._state.current_phase == phase and rec.ended_at is None
            duration = (
                rec.ended_at if rec.ended_at is not None else total_elapsed
            ) - rec.started_at
            label = _PHASE_LABEL[phase]
            emoji = _PHASE_EMOJI[phase]

            parts = [f"  {emoji} {label}"]
            if rec.detail:
                parts.append(f"[#a0a0a0]{rec.detail}[/#a0a0a0]")
            if rec.progress is not None and is_active:
                pct = int(round(rec.progress * 100))
                parts.append(f"[#7fc090]{_format_progress_bar(rec.progress)}[/#7fc090] {pct}%")
            parts.append(f"[dim]\\[{_format_seconds(duration)}\\][/dim]")
            if not is_active:
                parts.append("[#7fc090]✓[/#7fc090]")
            lines.append("  ".join(parts))

        if self._state.current_phase == "error":
            rec = self._state.phases["error"]
            duration = (rec.ended_at or total_elapsed) - rec.started_at
            lines.append(
                f"  ✗ [#cb4b4b]{rec.detail or 'error'}[/#cb4b4b]  "
                f"[dim]\\[{_format_seconds(duration)}\\][/dim]"
            )
        elif self._state.current_phase == "done" and self._state.final_summary:
            lines.append(
                f"  [#7fc090]Summary:[/#7fc090] {self._state.final_summary}  "
                f"[dim]\\[{_format_seconds(total_elapsed)} total\\][/dim]"
            )

        return "\n".join(lines)

    def _refresh(self) -> None:
        from contextlib import suppress

        with suppress(Exception):
            # Widget not yet mounted or already removed. Suppress —
            # the ticker fires regardless of mount state.
            self.query_one("#card-body", Static).update(self.render_body())

    def _stop_ticker(self) -> None:
        if self._tick_handle is not None:
            self._tick_handle.stop()
            self._tick_handle = None


__all__ = [
    "OperationCard",
    "OperationState",
    "Phase",
    "PhaseRecord",
]
