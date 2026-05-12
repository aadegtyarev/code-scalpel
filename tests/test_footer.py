"""Footer rendering — hints / status / ctx / model segments."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Label

from code_scalpel.tui.widgets.footer import StatusFooter


class _Harness(App[None]):
    def compose(self) -> ComposeResult:
        yield StatusFooter()


@pytest.mark.asyncio
async def test_footer_default_has_no_ctx_segment() -> None:
    """Empty ctx reactive → segment omitted entirely (no dangling `ctx`)."""
    app = _Harness()
    async with app.run_test(headless=True, size=(80, 5)) as pilot:
        await pilot.pause(0.05)
        footer = app.query_one(StatusFooter)
        rendered = str(footer.query_one("#footer-label", Label).render())
        assert "ctx" not in rendered


@pytest.mark.asyncio
async def test_footer_shows_ctx_when_set() -> None:
    """Once Session has data the app sets `ctx`; the segment appears
    with the `ctx` prefix the user expects to scan for."""
    app = _Harness()
    async with app.run_test(headless=True, size=(80, 5)) as pilot:
        await pilot.pause(0.05)
        footer = app.query_one(StatusFooter)
        footer.ctx = "4k/16k (26%)"
        await pilot.pause(0.05)
        rendered = str(footer.query_one("#footer-label", Label).render())
        assert "ctx 4k/16k (26%)" in rendered


@pytest.mark.asyncio
async def test_footer_ctx_updates_live() -> None:
    """Ctx is continuous state — typing moves it. Setting reactive twice
    must propagate both updates to the label."""
    app = _Harness()
    async with app.run_test(headless=True, size=(80, 5)) as pilot:
        await pilot.pause(0.05)
        footer = app.query_one(StatusFooter)
        footer.ctx = "2k/16k (12%)"
        await pilot.pause(0.05)
        footer.ctx = "8k/16k (50%)"
        await pilot.pause(0.05)
        rendered = str(footer.query_one("#footer-label", Label).render())
        assert "ctx 8k/16k (50%)" in rendered
        assert "12%" not in rendered


@pytest.mark.asyncio
async def test_footer_segments_order_is_stable() -> None:
    """hints · status · ctx · model — testing the order in one render so
    a future refactor that reshuffles segments fails loud here."""
    app = _Harness()
    async with app.run_test(headless=True, size=(140, 5)) as pilot:
        await pilot.pause(0.05)
        footer = app.query_one(StatusFooter)
        footer.status = "● running"
        footer.ctx = "1k/16k (6%)"
        footer.model = "qwen-coder-14b"
        await pilot.pause(0.05)
        rendered = str(footer.query_one("#footer-label", Label).render())
        # Rich strips the [tab] / [q] bracket-markup; check via the literal
        # "mode" word that survives in the hints chunk.
        i_hints = rendered.index("mode")
        i_status = rendered.index("● running")
        i_ctx = rendered.index("ctx")
        i_model = rendered.index("qwen-coder-14b")
        assert i_hints < i_status < i_ctx < i_model


@pytest.mark.asyncio
async def test_footer_no_idle_by_default() -> None:
    """Empty status means idle — no 'idle' text clutters the footer."""
    app = _Harness()
    async with app.run_test(headless=True, size=(80, 5)) as pilot:
        await pilot.pause(0.05)
        footer = app.query_one(StatusFooter)
        assert footer.status == ""
        rendered = str(footer.query_one("#footer-label", Label).render())
        assert "idle" not in rendered


@pytest.mark.asyncio
async def test_footer_trust_indicator_shown() -> None:
    """Trust reactive renders its short form in the label."""
    app = _Harness()
    async with app.run_test(headless=True, size=(140, 5)) as pilot:
        await pilot.pause(0.05)
        footer = app.query_one(StatusFooter)
        footer.trust = "[skp]"
        await pilot.pause(0.05)
        rendered = str(footer.query_one("#footer-label", Label).render())
        assert "[skp]" in rendered


@pytest.mark.asyncio
async def test_footer_thinking_indicator_shown_and_hidden() -> None:
    """Thinking reactive appears when set, disappears when cleared."""
    app = _Harness()
    async with app.run_test(headless=True, size=(140, 5)) as pilot:
        await pilot.pause(0.05)
        footer = app.query_one(StatusFooter)
        footer.thinking = "◐ med"
        await pilot.pause(0.05)
        rendered = str(footer.query_one("#footer-label", Label).render())
        assert "◐ med" in rendered

        footer.thinking = ""
        await pilot.pause(0.05)
        rendered = str(footer.query_one("#footer-label", Label).render())
        assert "◐" not in rendered


@pytest.mark.asyncio
async def test_footer_trust_before_thinking_in_indicators() -> None:
    """trust appears before thinking in the indicators group."""
    app = _Harness()
    async with app.run_test(headless=True, size=(200, 5)) as pilot:
        await pilot.pause(0.05)
        footer = app.query_one(StatusFooter)
        footer.trust = "[opt]"
        footer.thinking = "◐ high"
        await pilot.pause(0.05)
        rendered = str(footer.query_one("#footer-label", Label).render())
        assert rendered.index("[opt]") < rendered.index("◐ high")


@pytest.mark.asyncio
async def test_footer_status_empty_skipped_in_label() -> None:
    """Empty status must not produce a dangling '·' separator."""
    app = _Harness()
    async with app.run_test(headless=True, size=(80, 5)) as pilot:
        await pilot.pause(0.05)
        footer = app.query_one(StatusFooter)
        footer.status = ""
        footer.trust = "[skp]"
        await pilot.pause(0.05)
        rendered = str(footer.query_one("#footer-label", Label).render())
        # No double-separator from an empty status slot
        assert " ·  · " not in rendered
        assert "[skp]" in rendered
