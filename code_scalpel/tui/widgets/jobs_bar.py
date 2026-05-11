"""Inline strip above the footer surfacing live background jobs.

Subscribes to a JobRegistry on mount; rerenders on every snapshot
update. Hides itself (display=False, height=0) when there's nothing
running so it doesn't take a row of chrome from the user during idle.

Renders as a single line:

    ⚙ 2 jobs: map · step

The bar deliberately stays terse — the user doesn't need durations or
ids in the steady-state view, just "what's busy right now". Job kinds
already encode the work shape (map / step / tests). For details Ctrl+J
can later open a modal; this widget owns the at-a-glance view only.
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label

from code_scalpel.jobs import Job, JobRegistry


class JobsBar(Widget):
    DEFAULT_CSS = """
    JobsBar {
        height: 0;
        display: none;
        background: #1c1c1c;
        color: #888888;
        padding: 0 1;
    }
    JobsBar.live {
        height: 1;
        display: block;
    }
    JobsBar Label {
        color: #888888;
    }
    """

    # Last snapshot we rendered. Reactive so Textual handles the
    # mount-time first render and any subsequent updates uniformly.
    jobs: reactive[tuple[Job, ...]] = reactive(())

    def __init__(self, registry: JobRegistry) -> None:
        super().__init__()
        self._registry = registry
        self._unsubscribe: Callable[[], None] | None = None

    def compose(self) -> ComposeResult:
        yield Label("", id="jobs-bar-label")

    def on_mount(self) -> None:
        # All our existing workers are async coroutines running on the
        # event loop (asyncio.to_thread / loop.run_in_executor jobs
        # finish their I/O on a pool but call back into the loop before
        # touching the registry). Direct reactive assignment is safe
        # there. The cross-thread branch is for future plugins that
        # might `reg.start()` from a raw threading.Thread — without
        # `call_from_thread` the reactive set would crash the worker.
        main_thread = threading.main_thread()

        def _on_change(snap: tuple[Job, ...]) -> None:
            if threading.current_thread() is main_thread:
                self._set_jobs(snap)
                return
            # App is shutting down → drop the update on the floor rather
            # than crashing the worker mid-finalize.
            with contextlib.suppress(RuntimeError):
                self.app.call_from_thread(self._set_jobs, snap)

        self._unsubscribe = self._registry.subscribe(_on_change)
        # Seed with the current snapshot in case jobs were registered
        # before we mounted (race-safe).
        self._set_jobs(self._registry.snapshot())

    def on_unmount(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

    def _set_jobs(self, snap: tuple[Job, ...]) -> None:
        self.jobs = snap

    def watch_jobs(self, snap: tuple[Job, ...]) -> None:
        if not snap:
            self.remove_class("live")
        else:
            self.add_class("live")
        self._refresh_label()

    def _refresh_label(self) -> None:
        snap = self.jobs
        if not snap:
            text = ""
        else:
            kinds = " · ".join(j.kind for j in snap)
            count = len(snap)
            noun = "job" if count == 1 else "jobs"
            text = f"⚙ {count} {noun}: {kinds}"
        with contextlib.suppress(Exception):
            self.query_one("#jobs-bar-label", Label).update(text)
