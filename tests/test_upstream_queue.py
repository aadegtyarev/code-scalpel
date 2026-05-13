"""Pending queue + flush flow for upstream forks (v0.12 PR-C2).

The queue + flush split is the architecture-defining piece: forks
collected during /go are resolved en masse at the end, with
overrides surfaced for the user to review. Tests cover queue
mechanics, end-to-end flush through Runtime, and the
HumanForker→queue handoff."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from code_scalpel.config import AgentConfig, AppConfig, ModelProfile
from code_scalpel.fork import (
    ForkOption,
    ForkResolution,
    UpstreamProfile,
)
from code_scalpel.llm.lmstudio_swap import set_test_transport
from code_scalpel.runtime import Runtime
from code_scalpel.upstream_queue import (
    FlushSummary,
    PendingFork,
    UpstreamPendingQueue,
)
from tests.mocks import MockLLMAdapter


@pytest.fixture(autouse=True)
def _no_real_swap() -> object:
    """flush_upstream обёрнут в swap_to, который дёргает реальную
    LM Studio через httpx. В юнит-тестах подменяем transport на
    no-op mock: на любой /models, /models/load, /models/unload
    отвечаем 200 c пустыми данными — swap_to при этом
    проваливается через цикл без падений."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/models") and request.method == "GET":
            return httpx.Response(200, json={"models": []})
        if path.endswith("/models/load"):
            return httpx.Response(200, json={"instance_id": "stub", "status": "loaded"})
        if path.endswith("/models/unload"):
            return httpx.Response(200, json={"instance_id": "stub"})
        return httpx.Response(404, json={"error": "not mocked"})

    set_test_transport(httpx.MockTransport(handler))
    yield None
    set_test_transport(None)


# ── Queue mechanics ──────────────────────────────────────────────


def _fork(fork_id: str = "id1", chosen: str = "a") -> PendingFork:
    return PendingFork(
        fork_id=fork_id,
        question="any?",
        options=(ForkOption("a", "first"), ForkOption("b", "second")),
        context="ctx",
        picker_resolution=ForkResolution(chosen=chosen, reasoning="picker"),
    )


def test_queue_starts_empty() -> None:
    q = UpstreamPendingQueue()
    assert q.is_empty()
    assert q.pending_count() == 0
    assert q.drain() == []


def test_enqueue_and_count() -> None:
    q = UpstreamPendingQueue()
    q.enqueue(_fork("a"))
    q.enqueue(_fork("b"))
    assert q.pending_count() == 2
    assert not q.is_empty()


def test_record_commit_appends_to_every_pending_fork() -> None:
    """A task's commit is potentially relevant to every pending
    fork — we don't know per-fork scope, so we annotate all of
    them. The user narrows during /review-overrides if needed."""
    q = UpstreamPendingQueue()
    q.enqueue(_fork("a"))
    q.enqueue(_fork("b"))
    q.record_commit("abc1234")
    q.record_commit("def5678")
    drained = q.drain()
    sha_lists = {f.fork_id: shas for f, shas in drained}
    assert sha_lists["a"] == ["abc1234", "def5678"]
    assert sha_lists["b"] == ["abc1234", "def5678"]


def test_record_commit_with_empty_queue_is_noop() -> None:
    """Tasks before any fork was enqueued shouldn't accumulate
    commits — there's nothing to attribute them to."""
    q = UpstreamPendingQueue()
    q.record_commit("abc")
    q.enqueue(_fork("a"))
    drained = q.drain()
    assert drained[0][1] == []


def test_drain_clears_state() -> None:
    q = UpstreamPendingQueue()
    q.enqueue(_fork("a"))
    q.record_commit("abc")
    q.drain()
    assert q.is_empty()
    assert q.drain() == []


def test_snapshot_does_not_mutate() -> None:
    """`/escalate --preview` reads pending forks without consuming.
    The snapshot returns a list copy so the actual queue stays
    intact for a real flush later."""
    q = UpstreamPendingQueue()
    q.enqueue(_fork("a"))
    snap = q.snapshot()
    assert len(snap) == 1
    assert not q.is_empty()  # still pending


def test_flush_summary_line() -> None:
    s = FlushSummary(confirms=3, overrides=())
    assert "3 forks" in s.render_summary_line()
    assert "3 confirmed" in s.render_summary_line()


def test_flush_summary_single_fork_no_plural() -> None:
    """One fork should read «1 fork», not «1 forks». Cosmetic but
    visible in every release summary."""
    s = FlushSummary(confirms=1, overrides=())
    line = s.render_summary_line()
    assert "1 fork," in line or line.startswith("1 fork")
    assert "1 forks" not in line


# ── Runtime integration ──────────────────────────────────────────


@pytest.fixture
def project(tmp_path: Path) -> Path:
    return tmp_path


def _make_runtime(project: Path, *, upstream: UpstreamProfile | None = None) -> Runtime:
    cfg = AppConfig(
        profiles={"local": ModelProfile(provider="lmstudio", model="local-m")},
        agent=AgentConfig(max_files=2, max_file_lines=50, enforce_read_before_show=False),
    )
    llm = MockLLMAdapter(['{"chosen": "a", "reasoning": "ok"}'] * 10)
    return Runtime(
        cwd=project,
        config=cfg,
        llm=llm,
        with_memory=False,
        upstream_profile=upstream,
    )


@pytest.mark.asyncio
async def test_runtime_without_upstream_has_no_queue(project: Path) -> None:
    """No upstream profile → no queue, no flush. flush_upstream is
    a no-op that returns an empty summary — callers can invoke
    unconditionally."""
    runtime = _make_runtime(project, upstream=None)
    assert runtime.upstream_queue is None
    summary = await runtime.flush_upstream()
    assert summary.total == 0


@pytest.mark.asyncio
async def test_runtime_with_upstream_enqueues_on_fork(project: Path) -> None:
    """With upstream attached, the Auto path through HumanForker
    enqueues a fork (with the temporary picker resolution) instead
    of just returning it. Builder still gets the picker answer to
    keep going."""
    runtime = _make_runtime(
        project, upstream=UpstreamProfile(base_url="http://localhost:1234/v1", model="big")
    )
    # Force the upstream queueing branch — trust=yolo + critical=False
    # delegates straight to _delegate_to_local_meta which calls
    # _enqueue_for_upstream when queue is set.
    runtime.config.agent.trust = "yolo"
    runtime.config.agent.fork_auto_reviewed = False  # one LLM call, not two

    res = await runtime.fork(
        "Q?",
        (ForkOption("a", "first"), ForkOption("b", "second")),
        "ctx",
        critical=False,
    )
    # Builder gets the picker answer immediately.
    assert res.chosen == "a"
    # And the queue has the entry waiting for flush.
    assert runtime.upstream_queue is not None
    assert runtime.upstream_queue.pending_count() == 1
    pending = runtime.upstream_queue.snapshot()[0]
    assert pending.picker_resolution.chosen == "a"
    assert pending.question == "Q?"


@pytest.mark.asyncio
async def test_flush_upstream_confirms_and_overrides(project: Path) -> None:
    """End-to-end: enqueue two forks, mock upstream HTTP to return
    one confirm (chose 'a' just like picker) and one override
    (upstream picks 'b' where picker picked 'a'). Summary
    distinguishes them."""
    runtime = _make_runtime(
        project, upstream=UpstreamProfile(base_url="http://localhost:1234/v1", model="big")
    )
    runtime.config.agent.trust = "yolo"
    runtime.config.agent.fork_auto_reviewed = False
    # Two picker calls each return 'a' (the MockLLMAdapter loop).
    await runtime.fork("First question?", (ForkOption("a", ""), ForkOption("b", "")), "ctx")
    await runtime.fork("Second question?", (ForkOption("a", ""), ForkOption("b", "")), "ctx")
    assert runtime.upstream_queue is not None
    assert runtime.upstream_queue.pending_count() == 2

    # Upstream returns 'a' for the first fork (confirm) and 'b'
    # for the second (override). The SSE bodies are minimal — just
    # the message.delta with the JSON resolution.
    bodies = [
        b'data: {"type": "message.delta", "content": '
        b'"{\\"chosen\\": \\"a\\", \\"reasoning\\": \\"agree\\"}"}\n'
        b'data: {"type": "chat.end", "result": {}}\n',
        b'data: {"type": "message.delta", "content": '
        b'"{\\"chosen\\": \\"b\\", \\"reasoning\\": \\"actually b\\"}"}\n'
        b'data: {"type": "chat.end", "result": {}}\n',
    ]
    call_idx = [0]

    def handler(request: httpx.Request) -> httpx.Response:
        body = bodies[call_idx[0]]
        call_idx[0] += 1
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    # Patch the UpstreamForker.resolve to use our mock transport.
    # Less invasive than monkeypatching httpx globally: we replace
    # the forker creation inside flush_upstream by patching the
    # class's _dispatch_native via a transport-aware AsyncClient
    # set on the UpstreamForker instance.
    from code_scalpel.fork import UpstreamForker

    original_dispatch = UpstreamForker._dispatch_native

    async def patched_dispatch(self, messages, options):  # type: ignore[no-untyped-def]
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            self._http_client = client
            return await original_dispatch(self, messages, options)

    UpstreamForker._dispatch_native = patched_dispatch  # type: ignore[assignment, method-assign]
    try:
        summary = await runtime.flush_upstream()
    finally:
        UpstreamForker._dispatch_native = original_dispatch  # type: ignore[assignment, method-assign]

    assert summary.confirms == 1
    assert len(summary.overrides) == 1
    assert summary.overrides[0].upstream_resolution.chosen == "b"
    assert summary.overrides[0].fork.picker_resolution.chosen == "a"
    assert "1 confirmed" in summary.render_summary_line()
    assert "1 override" in summary.render_summary_line()


@pytest.mark.asyncio
async def test_flush_upstream_collects_errors(project: Path) -> None:
    """Upstream call fails → error recorded, other forks still
    processed. Partial flush is better than total failure on a
    long /go run."""
    runtime = _make_runtime(
        project, upstream=UpstreamProfile(base_url="http://localhost:1234/v1", model="big")
    )
    runtime.config.agent.trust = "yolo"
    runtime.config.agent.fork_auto_reviewed = False
    await runtime.fork("Q?", (ForkOption("a", ""), ForkOption("b", "")), "ctx")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="server boom")

    from code_scalpel.fork import UpstreamForker

    original_dispatch = UpstreamForker._dispatch_native

    async def patched_dispatch(self, messages, options):  # type: ignore[no-untyped-def]
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            self._http_client = client
            return await original_dispatch(self, messages, options)

    UpstreamForker._dispatch_native = patched_dispatch  # type: ignore[assignment, method-assign]
    try:
        summary = await runtime.flush_upstream()
    finally:
        UpstreamForker._dispatch_native = original_dispatch  # type: ignore[assignment, method-assign]

    assert summary.confirms == 0
    assert len(summary.errors) == 1
    assert "boom" in summary.errors[0] or "500" in summary.errors[0]
