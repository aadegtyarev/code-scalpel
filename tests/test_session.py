"""Tests for Session — token tracking, compact baseline, summary line."""

from __future__ import annotations

from code_scalpel.llm.adapter import ChatResponse
from code_scalpel.session import Session


def _response(prompt: int = 0, completion: int = 0, cost: float | None = None) -> ChatResponse:
    return ChatResponse(content="", prompt_tokens=prompt, completion_tokens=completion, cost=cost)


def test_record_accumulates_tokens_and_cost() -> None:
    s = Session()
    s.record(_response(prompt=100, completion=50, cost=0.01))
    s.record(_response(prompt=200, completion=80, cost=0.02))

    assert s.total_prompt_tokens == 300
    assert s.total_completion_tokens == 130
    assert s.total_cost == 0.03
    assert s.requests == 2


def test_context_used_reflects_last_prompt_size() -> None:
    """Footer shows the cost of the next prompt — i.e. what we just sent,
    not the accumulated I/O. Completion tokens don't enter; the model
    isn't going to re-send its own output."""
    s = Session()
    s.record(_response(prompt=1000, completion=500))
    assert s.context_used_tokens == 1000


def test_mark_compacted_drops_context_used_to_zero() -> None:
    """After /compact the footer should report 0 used tokens — the prior
    history was just summarized away. The next turn will re-measure it."""
    s = Session()
    s.record(_response(prompt=2000, completion=1000))
    assert s.context_used_tokens == 2000

    s.mark_compacted()
    assert s.context_used_tokens == 0


def test_mark_compacted_preserves_cumulative_totals() -> None:
    """Cost summary on exit needs the lifetime totals — compact must not
    zero them, only the footer baseline."""
    s = Session()
    s.record(_response(prompt=5000, completion=2000, cost=0.05))
    s.mark_compacted()

    assert s.total_prompt_tokens == 5000
    assert s.total_completion_tokens == 2000
    assert s.total_cost == 0.05


def test_context_used_tracks_latest_prompt_after_compact() -> None:
    s = Session()
    s.record(_response(prompt=1000, completion=500))
    s.mark_compacted()
    s.record(_response(prompt=300, completion=150))

    assert s.context_used_tokens == 300
    # Totals reflect both pre- and post-compact usage.
    assert s.total_prompt_tokens == 1300
    assert s.total_completion_tokens == 650


def test_repeat_compact_rebaselines() -> None:
    """Each /compact zeroes the live indicator; the next record() fills
    it from the new prompt size, not from any accumulated delta."""
    s = Session()
    s.record(_response(prompt=1000, completion=500))
    s.mark_compacted()
    s.record(_response(prompt=400, completion=200))
    s.mark_compacted()
    s.record(_response(prompt=100, completion=50))

    assert s.context_used_tokens == 100


def test_detect_and_pin_language_caches_first_call() -> None:
    s = Session()
    assert s.detect_and_pin_language("привет") == "Russian"
    # Second call must not flip the pin even if the new text is in English.
    assert s.detect_and_pin_language("hello") == "Russian"


def test_stats_report_lists_core_fields() -> None:
    s = Session()
    s.record(_response(prompt=120, completion=80, cost=0.0050))
    s.record(_response(prompt=200, completion=160))
    report = s.stats_report(ctx_limit=16384, model="qwen/qwen2.5-coder-14b", mode="ask")
    assert "qwen/qwen2.5-coder-14b" in report
    assert "ask" in report
    assert "requests" in report
    assert "320" in report  # prompt total
    assert "240" in report  # completion total
    assert "16384" in report
    assert "$0.0050" in report


def test_stats_report_omits_optional_when_not_provided() -> None:
    """No model / mode / ctx_limit / cost → those rows simply don't appear,
    rather than rendering blank values."""
    s = Session()
    s.record(_response(prompt=50, completion=30))
    report = s.stats_report()
    assert "requests" in report
    assert "tokens" in report
    assert "model" not in report
    assert "cost" not in report  # zero cost suppressed


def test_stats_report_surfaces_pinned_language() -> None:
    s = Session()
    s.detect_and_pin_language("Привет!")
    report = s.stats_report()
    assert "language" in report
    assert "Russian" in report


def test_stats_report_marks_compact_baseline_once_set() -> None:
    s = Session()
    s.record(_response(prompt=1000, completion=400))
    s.mark_compacted()
    report = s.stats_report()
    assert "compacted at" in report
    assert "1400" in report
