"""Per-session registry of background jobs.

The TUI has multiple long-running operations going at once: an LLM
stream, a `/map` build, a pytest retry loop, the agent's `read_file`
chain. Today each updates the footer independently and the user can't
tell what's actually running. The registry centralises that: every
worker registers a `Job` on start, finishes it on completion, and a
`JobsBar` widget renders the live list inline.

This module is intentionally framework-agnostic — it knows nothing
about Textual. The TUI subscribes via `JobRegistry.subscribe` and gets
a callback every time the snapshot changes; that callback turns into
a widget refresh on the Textual side.

Plugin-friendly: anything that wants to expose progress (a custom
slash command, a third-party agent loop, a /go supervisor)
just acquires a JobRegistry handle and calls `track()`. No Textual
dependency, no app reach-around.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import count


@dataclass(frozen=True)
class Job:
    """One running background operation.

    `id` is monotonic across the registry's lifetime — duplicates would
    confuse listeners that key by id. `kind` is a short label (`map`,
    `step`, `tests`); `description` is a human sentence the bar can
    actually render. `started_at` is timezone-aware so age formatting
    survives across DST and the like.
    """

    id: int
    kind: str
    description: str
    started_at: datetime


_Listener = Callable[[tuple[Job, ...]], None]


@dataclass
class JobRegistry:
    _jobs: dict[int, Job] = field(default_factory=dict)
    _ids: Iterator[int] = field(default_factory=lambda: count(1))
    _listeners: list[_Listener] = field(default_factory=list)
    # The registry advertises "framework-agnostic, plugin-friendly" —
    # plugins might call start() / finish() from raw threading.Threads.
    # Without a lock, concurrent start() calls race on next(_ids) and
    # on _jobs.__setitem__. Lock is cheap; correctness is not optional.
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def start(self, kind: str, description: str) -> int:
        """Register a new job; returns its id. Caller is responsible for
        calling `finish(id)` — use `track()` to get the lifecycle for
        free when running inside a `with` block.
        """
        if not kind:
            raise ValueError("Job kind must be a non-empty label")
        if not description:
            raise ValueError("Job description must be a non-empty sentence")
        with self._lock:
            job_id = next(self._ids)
            self._jobs[job_id] = Job(
                id=job_id,
                kind=kind,
                description=description,
                started_at=datetime.now(UTC),
            )
        self._notify()
        return job_id

    def finish(self, job_id: int) -> None:
        """Remove a job. Idempotent — finishing an unknown id is a no-op
        so a `finally:` block after a crashed call doesn't double-fail."""
        with self._lock:
            removed = self._jobs.pop(job_id, None) is not None
        if removed:
            self._notify()

    @contextmanager
    def track(self, kind: str, description: str) -> Iterator[int]:
        """Lifecycle helper: register on enter, finish on exit (success
        or exception). The body sees the assigned job id in case it
        wants to update state through other channels later."""
        job_id = self.start(kind, description)
        try:
            yield job_id
        finally:
            self.finish(job_id)

    def snapshot(self) -> tuple[Job, ...]:
        """Immutable view of the current jobs, sorted by start time so
        the bar reads chronologically."""
        with self._lock:
            jobs = list(self._jobs.values())
        return tuple(sorted(jobs, key=lambda j: j.started_at))

    def __len__(self) -> int:
        with self._lock:
            return len(self._jobs)

    def subscribe(self, listener: _Listener) -> Callable[[], None]:
        """Register a callback fired on every change. Returns an
        unsubscribe function — TUI widgets call it on unmount so a
        recycled registry doesn't keep references to dead widgets."""
        with self._lock:
            self._listeners.append(listener)

        def _unsubscribe() -> None:
            with self._lock, suppress(ValueError):
                self._listeners.remove(listener)

        return _unsubscribe

    def _notify(self) -> None:
        snap = self.snapshot()
        # Copy under lock so a concurrent subscribe/unsubscribe doesn't
        # mutate the iterator. Listener callbacks run outside the lock
        # — they're allowed to be slow (Textual reactive set, log write)
        # and must NOT deadlock if they reach back into the registry.
        with self._lock:
            listeners = list(self._listeners)
        # Listeners must not be allowed to crash the registry. A buggy
        # widget that throws inside its refresh handler shouldn't kill
        # the worker that triggered the notify.
        for listener in listeners:
            try:
                listener(snap)
            except Exception:
                continue
