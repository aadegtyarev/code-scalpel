"""Tests for the /context breakdown — pure-logic, no Textual."""

from __future__ import annotations

from code_scalpel.context_report import (
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
    # New format uses thousand-separated comma + full number.
    assert "1,000 / 16,000 tokens" in out
    assert "What's in context right now:" in out
    # All segments visible (Skills/Recipes added)
    for name in (
        "System prompt",
        "Tools schema",
        "Skills",
        "Recipes",
        "Project files",
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


def test_render_groups_used_with_explicit_subtotal() -> None:
    """The breakdown isn't just a flat list — used categories are
    grouped under "What's in context right now:" with an explicit
    subtotal row, and Free space sits separately under "Available:".
    Anchors the visual grouping so a future re-render doesn't
    silently lose the structure the user asked for."""
    report = build(
        model="m",
        ctx_limit=16000,
        system_prompt="x" * 4000,
        tools_schema_text="",
        overview_text="",
        recall_text="",
        history_text="",
    )
    out = report.render()
    assert "What's in context right now:" in out
    assert "Available:" in out
    # Tree-style elbows for the grouped list, not bare columns
    assert "┌─" in out and "└─" in out
    # Subtotal row mentions "used" with the sum
    assert "used" in out


def test_render_carries_short_notes_per_segment() -> None:
    """Each row should ship a short explanation note so the user
    sees WHAT and WHY at a glance, not just the absolute number."""
    report = build(
        model="m",
        ctx_limit=16000,
        system_prompt="x" * 4000,
        tools_schema_text="y" * 1000,
        overview_text="",
        recall_text="",
        history_text="",
    )
    out = report.render()
    # Sample notes appear (substring matches — full phrasing may shift)
    assert "static rules" in out
    assert "function-calling" in out
    # No Russian leaks in the UI surface
    assert "осталось" not in out
    assert "ужима" not in out


def test_render_includes_skills_and_recipes_segments() -> None:
    """Skills and Recipes are new categories — counters are 0 until
    SkillRegistry / learn are wired into the model prompt, but the
    slots exist in the breakdown so the user sees them."""
    report = build(
        model="m",
        ctx_limit=16000,
        system_prompt="",
        tools_schema_text="",
        overview_text="",
        recall_text="",
        history_text="",
    )
    out = report.render()
    assert "Skills" in out
    assert "Recipes" in out


def test_build_accepts_skills_and_recipes_text() -> None:
    """When the wiring lands, callers pass skills_text / recipes_text
    and those segments take their token cost. Defaults are empty."""
    report = build(
        model="m",
        ctx_limit=16000,
        system_prompt="",
        tools_schema_text="",
        overview_text="",
        recall_text="",
        history_text="",
        skills_text="x" * 400,  # 100t
        recipes_text="y" * 800,  # 200t
    )
    by_name = {s.name: s for s in report.segments}
    assert by_name["Skills"].tokens == 100
    assert by_name["Recipes"].tokens == 200
