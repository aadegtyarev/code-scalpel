"""Widget tests for JobsModal — the Ctrl+J full-view of background jobs."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from code_scalpel.jobs import JobRegistry
from code_scalpel.tui.widgets.jobs_modal import JobsModal, _fmt_age


class _Harness(App[None]):
    """App that pushes the modal on mount so Pilot can poke at it."""

    def __init__(self, registry: JobRegistry) -> None:
        super().__init__()
        self.registry = registry

    def compose(self) -> ComposeResult:
        yield from ()  # the modal lives on the screen stack, not in compose

    def on_mount(self) -> None:
        self.push_screen(JobsModal(self.registry))


def test_fmt_age_handles_seconds() -> None:
    """Right margin of each row is tight; ages need to fit predictably."""
    assert _fmt_age(0) == "0s"
    assert _fmt_age(59) == "59s"


def test_fmt_age_handles_minutes() -> None:
    assert _fmt_age(60) == "1m"
    assert _fmt_age(72) == "1m12s"
    assert _fmt_age(3599) == "59m59s"


def test_fmt_age_handles_hours() -> None:
    assert _fmt_age(3600) == "1h00m"
    assert _fmt_age(3725) == "1h02m"  # 1h 2min 5s → seconds dropped past the hour


@pytest.mark.asyncio
async def test_jobs_modal_shows_empty_state_when_idle() -> None:
    """Idle session — no jobs. The modal must still render with a clear
    'idle' notice instead of a blank box."""
    reg = JobRegistry()
    app = _Harness(reg)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        modal = app.screen
        assert isinstance(modal, JobsModal)
        empty = modal.query_one("#jm-empty")
        assert "idle" in str(empty.render()).lower()


@pytest.mark.asyncio
async def test_jobs_modal_lists_every_active_job() -> None:
    """Each job mounts as its own row. The kind label, description, and
    age fit-format must all reach the rendered output."""
    reg = JobRegistry()
    reg.start("map", "Building project map")
    reg.start("code-retry", "code: fix add bug")
    app = _Harness(reg)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        modal = app.screen
        assert isinstance(modal, JobsModal)
        rows = list(modal.query(".jm-row"))
        assert len(rows) == 2
        bodies = " ".join(str(r.render()) for r in rows)
        assert "map" in bodies
        assert "Building project map" in bodies
        assert "code-retry" in bodies
        assert "fix add bug" in bodies


@pytest.mark.asyncio
async def test_jobs_modal_header_shows_count() -> None:
    """The title carries the live count — gives the user a glance answer
    before they scan the rows."""
    reg = JobRegistry()
    reg.start("map", "x")
    reg.start("step", "y")
    reg.start("compact", "z")
    app = _Harness(reg)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        modal = app.screen
        assert isinstance(modal, JobsModal)
        header = modal.query_one("#jm-header")
        rendered = str(header.render())
        assert "3" in rendered
