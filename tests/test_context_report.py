"""Tests for the /context breakdown — pure-logic, no Textual."""

from __future__ import annotations

from code_scalpel.context_report import (
    ContextSegment,
    _tokens,
    build,
)


def test_token_estimate_uses_four_chars_per_token() -> None:
    """Same heuristic Session.record uses for cost — picking a different
    ratio here would mean /context and /stats report different sizes
    for the same data."""
    assert _tokens("x" * 400) == 100
    assert _tokens("") == 0


def test_build_sums_segments_into_used() -> None:
    report = build(
        model="qwen-coder-14b",
        ctx_limit=16000,
        system_prompt="x" * 4000,  # 1000 tokens
        tools_schema_text="y" * 2000,  # 500 tokens
        overview_text="z" * 800,  # 200 tokens
        recall_text="",
        history_text="w" * 400,  # 100 tokens
    )
    # 1000 + 500 + 200 + 0 + 100 = 1800
    assert report.used_tokens == 1800


def test_build_computes_free_space_when_limit_known() -> None:
    report = build(
        model="m",
        ctx_limit=16000,
        system_prompt="x" * 4000,
        tools_schema_text="",
        overview_text="",
        recall_text="",
        history_text="",
    )
    by_name = {s.name: s for s in report.segments}
    assert "Free space" in by_name
    assert by_name["Free space"].tokens == 15000


def test_build_clamps_free_space_to_zero_on_overflow() -> None:
    """History past the limit can happen before /compact fires. The
    "used" number signals over-budget; "Free space" stays at 0 rather
    than going negative — a negative row is meaningless and ugly."""
    report = build(
        model="m",
        ctx_limit=1000,
        system_prompt="x" * 80_000,  # 20k tokens, way over 1k limit
        tools_schema_text="",
        overview_text="",
        recall_text="",
        history_text="",
    )
    by_name = {s.name: s for s in report.segments}
    assert by_name["Free space"].tokens == 0


def test_build_omits_free_segment_when_limit_unknown() -> None:
    """No ctx_limit yet (autodetect hasn't fired or LM Studio is
    silent) — Free space is meaningless; segment is dropped instead
    of rendering with placeholder zeros."""
    report = build(
        model="m",
        ctx_limit=0,
        system_prompt="x" * 4000,
        tools_schema_text="",
        overview_text="",
        recall_text="",
        history_text="",
    )
    names = [s.name for s in report.segments]
    assert "Free space" not in names


def test_segments_carry_percent_when_limit_known() -> None:
    report = build(
        model="m",
        ctx_limit=16000,
        system_prompt="x" * 4000,
        tools_schema_text="",
        overview_text="",
        recall_text="",
        history_text="",
    )
    sys_seg = next(s for s in report.segments if s.name == "System prompt")
    assert sys_seg.percent is not None
    assert abs(sys_seg.percent - 6.25) < 0.01  # 1000 / 16000


def test_segments_percent_is_none_without_limit() -> None:
    report = build(
        model="m",
        ctx_limit=0,
        system_prompt="x" * 400,
        tools_schema_text="",
        overview_text="",
        recall_text="",
        history_text="",
    )
    for seg in report.segments:
        assert seg.percent is None


def test_render_contains_model_and_used_line() -> None:
    report = build(
        model="qwen2.5-coder-14b",
        ctx_limit=16000,
        system_prompt="x" * 4000,
        tools_schema_text="",
        overview_text="",
        recall_text="",
        history_text="",
    )
    out = report.render()
    assert "qwen2.5-coder-14b" in out
    assert "1k / 16k tokens" in out
    assert "Estimated breakdown" in out
    # All six segments visible
    for name in (
        "System prompt",
        "Tools schema",
        "Overview",
        "Memory recall",
        "Conversation",
        "Free space",
    ):
        assert name in out


def test_render_handles_unknown_limit_gracefully() -> None:
    report = build(
        model="m",
        ctx_limit=0,
        system_prompt="x" * 4000,
        tools_schema_text="",
        overview_text="",
        recall_text="",
        history_text="",
    )
    out = report.render()
    assert "ctx limit unknown" in out
    assert "Free space" not in out  # also dropped from segments


def test_render_progress_bar_uses_unicode_blocks() -> None:
    """40-char bar — verify a known percent renders the expected number
    of filled blocks. Anchors against a future refactor that swaps the
    bar chars or width."""
    report = build(
        model="m",
        ctx_limit=16000,
        system_prompt="x" * (4000 * 4),  # exactly 4000 tokens = 25%
        tools_schema_text="",
        overview_text="",
        recall_text="",
        history_text="",
    )
    out = report.render()
    # 25% of 40 = 10 filled blocks
    assert "█" * 10 in out
    assert "░" in out


def test_segment_render_aligns_label_column() -> None:
    """Labels right-padded to a common width so the token-count column
    lines up visually. Anchor test on a synthetic segment so the
    expectations don't drift with new categories."""
    seg = ContextSegment("Short", 100, 5.0)
    out = seg.render(label_width=20)
    assert out.startswith("  Short" + " " * 15)  # 20 - len("Short") = 15
