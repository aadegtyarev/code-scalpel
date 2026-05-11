"""Tests for the background job registry — pure-logic, no Textual."""

from __future__ import annotations

import pytest

from code_scalpel.jobs import Job, JobRegistry


def test_start_returns_monotonic_ids() -> None:
    r = JobRegistry()
    a = r.start("map", "Building map")
    b = r.start("step", "Generating reply")
    assert a == 1
    assert b == 2


def test_start_rejects_empty_kind_or_description() -> None:
    """Empty labels would render as a hole in the bar — fail loud."""
    r = JobRegistry()
    with pytest.raises(ValueError):
        r.start("", "desc")
    with pytest.raises(ValueError):
        r.start("kind", "")


def test_finish_removes_job() -> None:
    r = JobRegistry()
    a = r.start("map", "Building")
    r.start("step", "Streaming")
    r.finish(a)
    snap = r.snapshot()
    assert len(snap) == 1
    assert snap[0].kind == "step"


def test_finish_unknown_id_is_idempotent() -> None:
    """`finally: registry.finish(id)` runs even if the worker died
    before .start ran. Treat unknown ids as a no-op so the same finally
    block is safe across crash paths."""
    r = JobRegistry()
    r.finish(9999)  # must not raise


def test_snapshot_sorted_by_start_time() -> None:
    """Chronological order keeps the JobsBar readable: oldest first."""
    r = JobRegistry()
    r.start("a", "first")
    r.start("b", "second")
    r.start("c", "third")
    descriptions = [j.description for j in r.snapshot()]
    assert descriptions == ["first", "second", "third"]


def test_track_registers_and_cleans_up() -> None:
    """`with track(...)` is the recommended pattern — covers happy path."""
    r = JobRegistry()
    with r.track("map", "Building"):
        assert len(r) == 1
    assert len(r) == 0


def test_track_cleans_up_on_exception() -> None:
    """The whole point of the contextmanager is exception safety. A
    crashed worker mustn't leave a phantom job stuck in the bar."""
    r = JobRegistry()
    with pytest.raises(RuntimeError), r.track("step", "Streaming"):
        raise RuntimeError("boom")
    assert len(r) == 0


def test_subscribe_fires_on_start_and_finish() -> None:
    r = JobRegistry()
    events: list[tuple[Job, ...]] = []
    r.subscribe(events.append)
    jid = r.start("map", "B")
    r.finish(jid)
    # Two notifications: one after start, one after finish.
    assert [len(snap) for snap in events] == [1, 0]


def test_unsubscribe_stops_notifications() -> None:
    r = JobRegistry()
    received: list[tuple[Job, ...]] = []
    unsubscribe = r.subscribe(received.append)
    r.start("map", "B")
    unsubscribe()
    r.start("step", "S")
    assert len(received) == 1  # only the first start


def test_subscribe_isolates_broken_listeners() -> None:
    """A buggy widget throwing inside refresh must NOT prevent other
    listeners from receiving the same notification. The footer should
    stay live even if the inline bar widget crashes."""
    r = JobRegistry()
    seen: list[int] = []

    def broken(snap: tuple[Job, ...]) -> None:  # noqa: ARG001
        raise RuntimeError("widget exploded")

    def healthy(snap: tuple[Job, ...]) -> None:
        seen.append(len(snap))

    r.subscribe(broken)
    r.subscribe(healthy)
    r.start("map", "B")
    assert seen == [1]


def test_unsubscribe_is_idempotent() -> None:
    """Calling the unsubscribe handle twice (e.g. widget gets remounted
    and the cleanup runs again) must not raise."""
    r = JobRegistry()
    unsubscribe = r.subscribe(lambda snap: None)
    unsubscribe()
    unsubscribe()  # second call is a no-op
