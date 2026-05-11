"""Widget-level tests for JobsBar — keeps Textual integration in one place."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from code_scalpel.jobs import JobRegistry
from code_scalpel.tui.widgets.jobs_bar import JobsBar


class _Harness(App[None]):
    """Single-widget harness so Pilot can interact with the bar."""

    def __init__(self, registry: JobRegistry) -> None:
        super().__init__()
        self.registry = registry

    def compose(self) -> ComposeResult:
        yield JobsBar(self.registry)


@pytest.mark.asyncio
async def test_bar_hidden_when_no_jobs() -> None:
    """Idle session — no row of chrome stolen from the user."""
    reg = JobRegistry()
    app = _Harness(reg)
    async with app.run_test(headless=True, size=(80, 5)) as pilot:
        await pilot.pause(0.1)
        bar = app.query_one(JobsBar)
        assert not bar.has_class("live")


@pytest.mark.asyncio
async def test_bar_appears_with_job_and_shows_kind() -> None:
    """Starting one job must flip the bar to .live and render the kind."""
    from textual.widgets import Label

    reg = JobRegistry()
    app = _Harness(reg)
    async with app.run_test(headless=True, size=(80, 5)) as pilot:
        await pilot.pause(0.1)
        reg.start("map", "Building map")
        await pilot.pause(0.1)
        bar = app.query_one(JobsBar)
        assert bar.has_class("live")
        label = bar.query_one(Label)
        rendered = str(label.render())
        assert "map" in rendered
        assert "1 job" in rendered


@pytest.mark.asyncio
async def test_bar_pluralises_jobs() -> None:
    from textual.widgets import Label

    reg = JobRegistry()
    app = _Harness(reg)
    async with app.run_test(headless=True, size=(80, 5)) as pilot:
        await pilot.pause(0.1)
        reg.start("map", "Building map")
        reg.start("step", "Running ask turn")
        await pilot.pause(0.1)
        bar = app.query_one(JobsBar)
        rendered = str(bar.query_one(Label).render())
        assert "2 jobs" in rendered
        assert "map" in rendered
        assert "step" in rendered


@pytest.mark.asyncio
async def test_bar_disappears_when_jobs_finish() -> None:
    reg = JobRegistry()
    app = _Harness(reg)
    async with app.run_test(headless=True, size=(80, 5)) as pilot:
        await pilot.pause(0.1)
        jid = reg.start("map", "Building map")
        await pilot.pause(0.1)
        bar = app.query_one(JobsBar)
        assert bar.has_class("live")
        reg.finish(jid)
        await pilot.pause(0.1)
        assert not bar.has_class("live")


@pytest.mark.asyncio
async def test_bar_unsubscribes_on_unmount() -> None:
    """Recycling the bar (e.g. /new wiping the chat) must not leave a
    dangling listener on the registry — otherwise the next session's
    bar gets duplicate callbacks."""
    reg = JobRegistry()
    app = _Harness(reg)
    async with app.run_test(headless=True, size=(80, 5)) as pilot:
        await pilot.pause(0.1)
        bar = app.query_one(JobsBar)
        await bar.remove()
        await pilot.pause(0.05)
    # After the app shuts down the listener list must be empty.
    assert reg._listeners == []
