"""Pending queue for upstream fork resolution.

When `upstream_profile` is configured, fork delegation becomes
batched: each Auto-path fork goes to LocalMetaForker (or
ReviewedAuto) as a **temporary** answer the builder uses to keep
moving, AND the original fork question + temporary resolution
land in this queue. Later — explicit `/escalate`, end of /go, or
a pending threshold — the queue is flushed: every entry goes
through UpstreamForker, the upstream answer is compared with the
temporary one, and differences are surfaced as override records
for the user to review.

We don't auto-rewrite code based on overrides. Builder may have
already committed work on the temporary answer; the override
record names which commits to look at (`commits_touched`). User
reviews via `/review-overrides` and decides.

Design notes:
- Queue is per-Runtime, not global — every Runtime has its own
  HumanForker that points at this queue.
- `commits_touched` is best-effort: collected by run_plan after
  each successful task. A fork resolved at plan-time is
  potentially relevant to every task that ran AFTER its
  resolution. Builder doesn't carve per-task scope (would
  require per-task fork annotation in TASKS.md); the simplifying
  assumption «all later tasks may depend on this fork» is
  honest given the data we have, and the user can narrow during
  review.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from code_scalpel.fork import ForkOption, ForkResolution


@dataclass(frozen=True)
class PendingFork:
    """One fork waiting for upstream flush. The temporary
    resolution is what the builder is currently working with;
    the upstream answer replaces it (or confirms it) at flush
    time."""

    fork_id: str  # stable id, used as a key in commits_touched_by
    question: str
    options: tuple[ForkOption, ...]
    context: str
    picker_resolution: ForkResolution  # the temporary answer

    @property
    def fingerprint(self) -> str:
        """Short identifier shown in the review UI / summary
        line. First N chars of question + chosen option name —
        deterministic, recognisable."""
        return f"{self.fork_id} ({self.picker_resolution.chosen})"


@dataclass(frozen=True)
class FlushOutcome:
    """Result of running one queued fork through upstream.

    `overridden=True` when picker and upstream disagreed on
    `chosen`. The TUI / summary picks this up to surface the
    override card. `commits_touched` is the list of git SHAs
    accumulated for this fork's id during the queue's lifetime.
    """

    fork: PendingFork
    upstream_resolution: ForkResolution
    overridden: bool
    commits_touched: tuple[str, ...]

    @property
    def is_confirm(self) -> bool:
        return not self.overridden


class UpstreamPendingQueue:
    """Mutable per-Runtime queue. Three operations:

    - `enqueue(...)` — HumanForker calls this when it routes a
      fork through the «temporary picker + queue it» path.
    - `record_commit(sha)` — run_plan calls this after each
      successful task, so we know which commits ran with the
      temporary answer in scope.
    - `drain()` — flush time. Returns the entries and clears
      state. Idempotent on empty queue (returns empty).

    Plain mutable state because the queue lives inside one
    asyncio loop; no need for locks. Tests mutate it directly.
    """

    def __init__(self) -> None:
        self._pending: list[PendingFork] = []
        # fork_id → list of commit SHAs that ran while this fork
        # was active (i.e. between enqueue and flush). All
        # currently-pending forks accumulate all commits — we
        # don't carve per-fork scope because a task can use any
        # plan-time decision.
        self._commits: dict[str, list[str]] = {}

    def enqueue(self, fork: PendingFork) -> None:
        self._pending.append(fork)
        self._commits.setdefault(fork.fork_id, [])

    def record_commit(self, sha: str) -> None:
        """A task just committed. Every pending fork potentially
        used this commit's work; append the sha to every entry's
        commit list. Empty queue → no-op."""
        if not sha or not self._pending:
            return
        for fork in self._pending:
            self._commits[fork.fork_id].append(sha)

    def pending_count(self) -> int:
        return len(self._pending)

    def is_empty(self) -> bool:
        return not self._pending

    def drain(self) -> list[tuple[PendingFork, list[str]]]:
        """Return all pending entries paired with their commit
        SHAs, clearing internal state. The caller passes each
        through UpstreamForker.resolve and builds FlushOutcome
        records.
        """
        out: list[tuple[PendingFork, list[str]]] = [
            (fork, list(self._commits.get(fork.fork_id, []))) for fork in self._pending
        ]
        self._pending = []
        self._commits = {}
        return out

    def snapshot(self) -> list[PendingFork]:
        """Read-only view for status displays — `/escalate
        --preview` listing pending forks before deciding to
        flush. Doesn't mutate state."""
        return list(self._pending)


@dataclass(frozen=True)
class FlushSummary:
    """Aggregated result the user / summary line cares about.

    `overrides` carries the forks where upstream disagreed —
    those need review. `confirms` is just a count so the
    summary can read «5 forks: 4 confirmed, 1 override».
    """

    confirms: int
    overrides: tuple[FlushOutcome, ...]
    errors: tuple[str, ...] = field(default_factory=tuple)

    @property
    def total(self) -> int:
        return self.confirms + len(self.overrides)

    def render_summary_line(self) -> str:
        """One-line digest for the /go end-of-run report."""
        parts = [f"{self.total} fork{'' if self.total == 1 else 's'}"]
        if self.confirms:
            parts.append(f"{self.confirms} confirmed")
        if self.overrides:
            parts.append(f"{len(self.overrides)} override{'' if len(self.overrides) == 1 else 's'}")
        if self.errors:
            parts.append(f"{len(self.errors)} error{'' if len(self.errors) == 1 else 's'}")
        return ", ".join(parts)


__all__ = [
    "FlushOutcome",
    "FlushSummary",
    "PendingFork",
    "UpstreamPendingQueue",
]
