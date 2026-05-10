from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from code_scalpel.tui.widgets.cards.tool_call import PatchDecision, ToolCallCard

SAMPLE_DIFF = """\
--- a/src/notes.py
+++ b/src/notes.py
@@ -14,1 +14,4 @@
-def search_notes(query):
+def search_notes(query: str = ""):
+    if not query:
+        return list_notes()
"""


def _make_app() -> tuple[App[None], list[str]]:
    decisions: list[str] = []

    class _CardApp(App[None]):
        def compose(self) -> ComposeResult:
            yield ToolCallCard("Apply", "src/notes.py")

        def on_patch_decision(self, msg: PatchDecision) -> None:
            decisions.append(msg.action)

    return _CardApp(), decisions


@pytest.mark.asyncio
async def test_initial_state_running() -> None:
    app, _ = _make_app()
    async with app.run_test() as pilot:
        card = app.query_one(ToolCallCard)
        assert card._state == "running"
        _ = pilot


@pytest.mark.asyncio
async def test_set_reviewing_shows_diff() -> None:
    app, _ = _make_app()
    async with app.run_test() as pilot:
        card = app.query_one(ToolCallCard)
        card.set_reviewing(SAMPLE_DIFF)
        await pilot.pause()
        assert card._state == "reviewing"
        assert card._diff == SAMPLE_DIFF


@pytest.mark.asyncio
async def test_set_done_success() -> None:
    app, _ = _make_app()
    async with app.run_test() as pilot:
        card = app.query_one(ToolCallCard)
        card.set_done("Applied 4 lines")
        await pilot.pause()
        assert card._state == "done"
        assert not card._error


@pytest.mark.asyncio
async def test_set_done_error() -> None:
    app, _ = _make_app()
    async with app.run_test() as pilot:
        card = app.query_one(ToolCallCard)
        card.set_done("patch does not apply", error=True)
        await pilot.pause()
        assert card._state == "error"
        assert card._error


@pytest.mark.asyncio
async def test_apply_key_posts_decision() -> None:
    app, decisions = _make_app()
    async with app.run_test() as pilot:
        card = app.query_one(ToolCallCard)
        card.set_reviewing(SAMPLE_DIFF)
        await pilot.pause()
        card.focus()
        await pilot.press("a")
        await pilot.pause()
        assert decisions == ["apply"]


@pytest.mark.asyncio
async def test_reject_key_posts_decision() -> None:
    app, decisions = _make_app()
    async with app.run_test() as pilot:
        card = app.query_one(ToolCallCard)
        card.set_reviewing(SAMPLE_DIFF)
        await pilot.pause()
        card.focus()
        await pilot.press("r")
        await pilot.pause()
        assert decisions == ["reject"]


@pytest.mark.asyncio
async def test_regen_key_posts_decision() -> None:
    app, decisions = _make_app()
    async with app.run_test() as pilot:
        card = app.query_one(ToolCallCard)
        card.set_reviewing(SAMPLE_DIFF)
        await pilot.pause()
        card.focus()
        await pilot.press("g")
        await pilot.pause()
        assert decisions == ["regen"]


@pytest.mark.asyncio
async def test_keys_ignored_when_not_reviewing() -> None:
    """Actions outside reviewing state must be no-ops."""
    app, decisions = _make_app()
    async with app.run_test() as pilot:
        card = app.query_one(ToolCallCard)
        card.focus()
        await pilot.press("a")
        await pilot.pause()
        assert decisions == []
