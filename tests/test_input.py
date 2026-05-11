"""Tests for ModeInput / HistoryInput — bash-style command history.

The textual-autocomplete dropdown used to hijack ↑/↓ for slash-command
navigation; the bindings on HistoryInput take priority so the user gets
the Linux-shell behaviour they expect: ↑ recalls previous commands, ↓
walks back toward the live draft.
"""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from code_scalpel.tui.widgets.input import HistoryInput, ModeInput, UserMessage


class _Harness(App[None]):
    """Minimal app hosting a single ModeInput — enough to drive Pilot."""

    def __init__(self) -> None:
        super().__init__()
        self.submitted: list[str] = []

    def compose(self) -> ComposeResult:
        yield ModeInput()

    def on_mount(self) -> None:
        self.query_one(ModeInput).focus_input()

    def on_user_message(self, event: UserMessage) -> None:
        self.submitted.append(event.text)


def test_push_history_dedupes_and_skips_empty() -> None:
    """Pure-logic check on push_history — no App needed for the buffer.
    Covers bash HISTCONTROL=ignoredups behaviour: consecutive duplicates
    fold; empty/whitespace lines are dropped; non-adjacent duplicates
    still record (alternating between two commands is valid history)."""
    h = HistoryInput()
    h.push_history("")
    h.push_history("   ")
    h.push_history("ls")
    h.push_history("ls")  # dup → ignored
    h.push_history("pwd")
    h.push_history("ls")  # non-adjacent dup → recorded
    assert h._history == ["ls", "pwd", "ls"]


def test_push_history_resets_browsing_cursor() -> None:
    """Submitting a fresh command must reset the browse cursor — otherwise
    the next ↑ would land on the wrong entry."""
    h = HistoryInput()
    h.push_history("one")
    h.push_history("two")
    h._idx = 0  # pretend we were browsing
    h._draft = "draft"
    h.push_history("three")
    assert h._idx is None
    assert h._draft == ""


@pytest.mark.asyncio
async def test_pilot_up_recalls_previous_submission() -> None:
    """End-to-end: type → enter → up → see previous text in the input."""
    app = _Harness()
    async with app.run_test(headless=True, size=(80, 5)) as pilot:
        await pilot.press("h", "i")
        await pilot.press("enter")
        await pilot.pause()
        assert app.submitted == ["hi"]

        await pilot.press("up")
        inp = app.query_one(HistoryInput)
        assert inp.value == "hi"


@pytest.mark.asyncio
async def test_pilot_down_does_not_open_dropdown_or_clobber_draft() -> None:
    """↓ on a fresh input must not affect the value — the slash-command
    dropdown used to steal ↓ to open itself."""
    app = _Harness()
    async with app.run_test(headless=True, size=(80, 5)) as pilot:
        await pilot.press("a", "b", "c")
        inp = app.query_one(HistoryInput)
        before = inp.value
        await pilot.press("down")
        assert inp.value == before


@pytest.mark.asyncio
async def test_pilot_up_then_down_returns_to_draft() -> None:
    """After ↑ recalls a past command, ↓ past the newest entry must
    restore the live draft the user was typing."""
    app = _Harness()
    async with app.run_test(headless=True, size=(80, 5)) as pilot:
        await pilot.press("o", "n", "e")
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("d", "r", "a", "f", "t")
        inp = app.query_one(HistoryInput)
        assert inp.value == "draft"
        await pilot.press("up")
        assert inp.value == "one"
        await pilot.press("down")
        # past newest → draft restored
        assert inp.value == "draft"


@pytest.mark.asyncio
async def test_pilot_up_walks_back_through_multiple_entries() -> None:
    """Two submissions, then two ↑ presses should land on the OLDEST."""
    app = _Harness()
    async with app.run_test(headless=True, size=(80, 5)) as pilot:
        await pilot.press("o", "n", "e")
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("t", "w", "o")
        await pilot.press("enter")
        await pilot.pause()
        assert app.submitted == ["one", "two"]

        inp = app.query_one(HistoryInput)
        await pilot.press("up")
        assert inp.value == "two"
        await pilot.press("up")
        assert inp.value == "one"
        # Clamp at oldest — extra ↑ stays on "one", doesn't error.
        await pilot.press("up")
        assert inp.value == "one"
