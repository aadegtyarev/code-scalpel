"""OperationCard — render logic + native-event ingestion.

The widget itself needs a Textual `App` context to mount, but the
phase-state machine and the render_body string-builder don't —
those we exercise directly. End-to-end mounting is covered by the
TUI smoke tests once PR-C wires UpstreamForker into the app.
"""

from __future__ import annotations

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
from code_scalpel.tui.widgets.cards.operation import (
    OperationCard,
    _format_progress_bar,
    _format_seconds,
)


def _make_card(title: str = "test") -> OperationCard:
    """Construct without mounting — we exercise the state machine
    directly. `on_mount` (which starts the ticker) is skipped on
    purpose; tests that need the ticker poll `_refresh` instead."""
    card = OperationCard(title=title)
    # The reactive __init__ already set up state; we just need the
    # ticker-less view of the world.
    return card


def test_progress_bar_renders_in_unicode() -> None:
    """Smoke check: a 50% bar at width 10 fills five cells with
    `▓` and the rest with `░`. The bar is the user-visible
    indicator of «loading 50%»; if the render shape regresses, the
    UI looks broken even though logic is fine."""
    bar = _format_progress_bar(0.5, width=10)
    assert bar == "▓▓▓▓▓░░░░░"


def test_progress_bar_clamps_out_of_range() -> None:
    """Defensive: ill-formed events shouldn't crash the renderer.
    Out-of-range progress clamps to 0/1."""
    assert _format_progress_bar(-0.5) == "░" * 10
    assert _format_progress_bar(1.5) == "▓" * 10


def test_format_seconds_short_long() -> None:
    """Short = `12.3s`, long = `1m 12s`. Matches Session footer."""
    assert _format_seconds(12.345) == "12.3s"
    assert _format_seconds(72.0) == "1m 12s"


def test_begin_opens_phase_once() -> None:
    """begin() is idempotent — server sometimes re-emits start
    events; we don't want to reset the timer if a phase is
    already running."""
    card = _make_card()
    card.begin("loading", detail="qwen-14b")
    rec_first = card._state.phases["loading"]
    card.begin("loading", detail="different detail")
    rec_second = card._state.phases["loading"]
    assert rec_first is rec_second
    assert rec_second.detail == "qwen-14b"


def test_set_phase_closes_previous() -> None:
    """Transition pattern: «I'm done loading, now processing» —
    one call, previous phase ends, new one opens."""
    card = _make_card()
    card.begin("loading")
    card.set_phase("processing", detail="8.2k tokens")
    assert card._state.phases["loading"].ended_at is not None
    assert card._state.current_phase == "processing"
    assert card._state.phases["processing"].detail == "8.2k tokens"


def test_set_progress_auto_opens_phase() -> None:
    """If the server jumps straight to model_load.progress without
    a model_load.start (it has happened), we still want to render
    something. set_progress opens the phase on demand."""
    card = _make_card()
    card.set_progress("loading", 0.42)
    assert "loading" in card._state.phases
    assert card._state.phases["loading"].progress == 0.42


def test_done_marks_completion_and_stops_ticker_safely() -> None:
    """done() with no prior phase still works — ticker is None
    because we never mounted. We just want done() to not crash
    on the unmounted code path."""
    card = _make_card()
    card.done("38 tokens, 12s")
    assert card._state.final_summary == "38 tokens, 12s"
    assert card._state.current_phase == "done"


def test_fail_records_error_detail() -> None:
    card = _make_card()
    card.begin("loading")
    card.fail("out of memory")
    assert card._state.current_phase == "error"
    assert "out of memory" in card._state.phases["error"].detail


def test_ingest_full_native_timeline() -> None:
    """End-to-end through the typed-event dispatcher. After the
    full cold-load + processing + generating + chat.end timeline,
    every phase should be closed, the done phase set, and the
    summary line populated from chat.end stats."""
    card = _make_card()
    card.ingest(ChatStart(model_instance_id="i1"))
    card.ingest(ModelLoadStart(model_instance_id="i1"))
    card.ingest(ModelLoadProgress(progress=0.5))
    card.ingest(ModelLoadProgress(progress=1.0))
    card.ingest(ModelLoadEnd(load_time_seconds=8.0))
    card.ingest(PromptProcessingStart())
    card.ingest(PromptProcessingProgress(progress=0.5))
    card.ingest(PromptProcessingEnd())
    card.ingest(MessageStart())
    card.ingest(MessageDelta(content="hi "))
    card.ingest(MessageDelta(content="there"))
    card.ingest(MessageEnd())
    card.ingest(ChatEnd(prompt_tokens=10, completion_tokens=2, total_time_seconds=12.0))

    assert card._state.current_phase == "done"
    assert card._state.phases["loading"].ended_at is not None
    assert card._state.phases["processing"].ended_at is not None
    assert card._state.phases["generating"].ended_at is not None
    assert "10 in" in card._state.final_summary
    assert "2 out" in card._state.final_summary
    # text was appended into the generating phase's detail tail
    assert "there" in card._state.phases["generating"].detail


def test_ingest_error_event_marks_failure() -> None:
    """Server emitted `error` mid-stream → card lands in error
    state with the message preserved for the user to see."""
    card = _make_card()
    card.ingest(ChatStart(model_instance_id="i1"))
    card.ingest(ModelLoadStart(model_instance_id="i1"))
    card.ingest(StreamError(message="context too long"))
    assert card._state.current_phase == "error"
    assert "context too long" in card._state.phases["error"].detail


def test_render_body_includes_active_progress() -> None:
    """Active loading phase with a known progress renders the bar
    and the percentage. This is what the user actually reads —
    don't let a refactor silently drop the bar."""
    card = _make_card("upstream flush")
    card.begin("loading", detail="gemma-26b")
    card.set_progress("loading", 0.42)
    body = card.render_body()
    assert "upstream flush" in body
    assert "gemma-26b" in body
    assert "42%" in body
    # progress bar uses unicode blocks
    assert "▓" in body


def test_render_body_completed_phase_shows_checkmark() -> None:
    card = _make_card()
    card.begin("loading")
    card.end_phase("loading")
    body = card.render_body()
    # ✓ marker present somewhere on the closed phase line
    assert "✓" in body


def test_render_body_error_state_visible() -> None:
    card = _make_card()
    card.begin("loading")
    card.fail("out of memory")
    body = card.render_body()
    assert "out of memory" in body
    assert "✗" in body
