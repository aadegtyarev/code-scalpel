"""Tests for ChoiceCard and ShellExecCard widgets."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from code_scalpel.tui.widgets.cards.choice import (
    ChoiceCard,
    ChoiceDecision,
    ChoiceOption,
)
from code_scalpel.tui.widgets.cards.shell_exec import ShellExecCard, ShellExecDecision

# ── Minimal host app ──────────────────────────────────────────────────────────


class _ChoiceApp(App[None]):
    """Minimal app that mounts a single ChoiceCard and collects messages."""

    def __init__(self, card: ChoiceCard) -> None:
        super().__init__()
        self._card = card
        self.decisions: list[ChoiceDecision] = []
        self.shell_decisions: list[ShellExecDecision] = []

    def compose(self) -> ComposeResult:
        yield self._card

    def on_choice_decision(self, msg: ChoiceDecision) -> None:
        self.decisions.append(msg)

    def on_shell_exec_decision(self, msg: ShellExecDecision) -> None:
        self.shell_decisions.append(msg)


# ── ChoiceCard: basic key dispatch ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_choice_card_posts_decision_on_key_press() -> None:
    """Pressing a registered option key posts ChoiceDecision with that key."""
    options = [
        ChoiceOption("a", "Alpha"),
        ChoiceOption("b", "Beta"),
    ]
    card = ChoiceCard(title="Pick one", options=options, card_id=42)
    app = _ChoiceApp(card)

    async with app.run_test(headless=True, size=(80, 10)) as pilot:
        await pilot.pause(0.1)
        card.focus()
        await pilot.press("a")
        await pilot.pause(0.1)

    assert len(app.decisions) == 1
    assert app.decisions[0].card_id == 42
    assert app.decisions[0].chosen_key == "a"


@pytest.mark.asyncio
async def test_choice_card_posts_correct_key_for_second_option() -> None:
    """Pressing the second option key uses that key, not the first."""
    options = [
        ChoiceOption("t", "Test"),
        ChoiceOption("p", "Plan"),
        ChoiceOption("m", "Manual"),
    ]
    card = ChoiceCard(title="Go mode", options=options, card_id=1)
    app = _ChoiceApp(card)

    async with app.run_test(headless=True, size=(80, 10)) as pilot:
        await pilot.pause(0.1)
        card.focus()
        await pilot.press("p")
        await pilot.pause(0.1)

    assert len(app.decisions) == 1
    assert app.decisions[0].chosen_key == "p"


# ── ChoiceCard: escape handling ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_choice_card_escape_when_cancel_on_escape_true() -> None:
    """ESC posts ChoiceDecision('esc') when cancel_on_escape=True."""
    options = [ChoiceOption("y", "Yes"), ChoiceOption("n", "No")]
    card = ChoiceCard(title="Confirm", options=options, card_id=7, cancel_on_escape=True)
    app = _ChoiceApp(card)

    async with app.run_test(headless=True, size=(80, 10)) as pilot:
        await pilot.pause(0.1)
        card.focus()
        await pilot.press("escape")
        await pilot.pause(0.1)

    assert len(app.decisions) == 1
    assert app.decisions[0].chosen_key == "esc"
    assert app.decisions[0].card_id == 7


@pytest.mark.asyncio
async def test_choice_card_escape_ignored_when_cancel_on_escape_false() -> None:
    """ESC does NOT post ChoiceDecision when cancel_on_escape=False."""
    options = [ChoiceOption("a", "approve"), ChoiceOption("r", "reject")]
    card = ChoiceCard(title="shell_exec", options=options, card_id=3, cancel_on_escape=False)
    app = _ChoiceApp(card)

    async with app.run_test(headless=True, size=(80, 10)) as pilot:
        await pilot.pause(0.1)
        card.focus()
        await pilot.press("escape")
        await pilot.pause(0.1)

    assert app.decisions == []


# ── ChoiceCard: hint format ───────────────────────────────────────────────────


def test_choice_card_hint_uses_round_brackets() -> None:
    """Keys are displayed as (a), not [a] — per the UX spec."""
    options = [ChoiceOption("a", "Alpha"), ChoiceOption("b", "Beta")]
    card = ChoiceCard(title="T", options=options, card_id=0)
    hint = card._hint_text()
    assert "(a)" in hint
    assert "(b)" in hint
    # Must NOT use square-bracket format
    assert "[a]" not in hint
    assert "[b]" not in hint


def test_choice_card_multi_line_hint_when_descriptions_present() -> None:
    """With descriptions the hint renders one option per line."""
    options = [
        ChoiceOption("t", "Test only", "run the suite"),
        ChoiceOption("p", "Full plan", "run all tasks"),
    ]
    card = ChoiceCard(title="Go", options=options, card_id=0)
    hint = card._hint_text()
    assert "\n" in hint  # multi-line
    assert "(t)" in hint
    assert "(p)" in hint
    assert "run the suite" in hint
    assert "run all tasks" in hint


def test_choice_card_inline_hint_when_no_descriptions() -> None:
    """Without descriptions the hint is a single inline line."""
    options = [ChoiceOption("a", "approve"), ChoiceOption("r", "reject")]
    card = ChoiceCard(title="T", options=options, card_id=0)
    hint = card._hint_text()
    assert "\n" not in hint
    assert "(a)" in hint
    assert "(r)" in hint


# ── ChoiceCard: state transitions ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_choice_card_ignores_keys_after_resolved() -> None:
    """A second key press after the card is resolved does nothing."""
    options = [ChoiceOption("a", "Alpha"), ChoiceOption("b", "Beta")]
    card = ChoiceCard(title="T", options=options, card_id=0)
    app = _ChoiceApp(card)

    async with app.run_test(headless=True, size=(80, 10)) as pilot:
        await pilot.pause(0.1)
        card.focus()
        await pilot.press("a")
        await pilot.pause(0.1)
        # Second press — card is in 'done' state and should ignore it.
        card.focus()
        await pilot.press("b")
        await pilot.pause(0.1)

    # Only the first decision is recorded.
    assert len(app.decisions) == 1
    assert app.decisions[0].chosen_key == "a"


# ── ShellExecCard: inheritance and message re-fire ────────────────────────────


def test_shell_exec_card_is_instance_of_choice_card() -> None:
    """ShellExecCard inherits ChoiceCard — isinstance check."""
    card = ShellExecCard(command="ls -la", card_id=0)
    assert isinstance(card, ChoiceCard)


@pytest.mark.asyncio
async def test_shell_exec_card_posts_shell_exec_decision_on_approve() -> None:
    """Pressing 'a' on ShellExecCard fires ShellExecDecision(action='approve'),
    not a raw ChoiceDecision."""
    card = ShellExecCard(command="rm -rf /tmp/test", card_id=5)
    app = _ChoiceApp(card)

    async with app.run_test(headless=True, size=(80, 10)) as pilot:
        await pilot.pause(0.1)
        card.focus()
        await pilot.press("a")
        await pilot.pause(0.1)

    assert len(app.shell_decisions) == 1
    assert app.shell_decisions[0].card_id == 5
    assert app.shell_decisions[0].action == "approve"
    # Raw ChoiceDecision must be stopped — app should NOT see it.
    assert app.decisions == []


@pytest.mark.asyncio
async def test_shell_exec_card_posts_shell_exec_decision_on_reject() -> None:
    """Pressing 'r' on ShellExecCard fires ShellExecDecision(action='reject')."""
    card = ShellExecCard(command="git push --force", card_id=9)
    app = _ChoiceApp(card)

    async with app.run_test(headless=True, size=(80, 10)) as pilot:
        await pilot.pause(0.1)
        card.focus()
        await pilot.press("r")
        await pilot.pause(0.1)

    assert len(app.shell_decisions) == 1
    assert app.shell_decisions[0].action == "reject"
    assert app.decisions == []


@pytest.mark.asyncio
async def test_shell_exec_card_does_not_handle_escape() -> None:
    """ShellExecCard uses cancel_on_escape=False — ESC is a no-op on the card."""
    card = ShellExecCard(command="echo hi", card_id=2)
    app = _ChoiceApp(card)

    async with app.run_test(headless=True, size=(80, 10)) as pilot:
        await pilot.pause(0.1)
        card.focus()
        await pilot.press("escape")
        await pilot.pause(0.1)

    assert app.decisions == []
    assert app.shell_decisions == []
