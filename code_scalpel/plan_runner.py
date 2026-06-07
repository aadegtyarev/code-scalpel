"""PlanRunner — the per-task autonomous execution loop, strangled out of agent.py.

`StepAgent.run_plan` delegates to `PlanRunner(self).run(...)`. The runner holds
a reference to the host `StepAgent` and reaches back through it for the
collaborators it needs (config, cwd, state, upstream queue, `code_with_retry`,
the git/test/verify helpers, persistence). This is the behavior-preserving
strangle (`feat/acceptance-gate-run-plan` commit 1): the loop body relocated
verbatim from `agent.py`, `self.` → `self._agent.`, so the existing run_plan
test suite passes unchanged.

The wide `PlanRunner(self)` coupling is deliberate for the safe move — the seam
the runner uses is documented in `.ai-pm/arch/acceptance-gate-run-plan_arch.md`
(Question 3) so a later opportunistic step can narrow it to explicit deps
without re-discovering the boundary.
"""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING

from code_scalpel.plan import Task, serialize_tasks
from code_scalpel.plan_post_checks import run_post_task_checks
from code_scalpel.plan_verify import verify_task
from code_scalpel.tools.agent_tools import ToolCall, ToolResult

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from code_scalpel.agent import RunPlanResult, StepAgent, StepResult, TaskOutcome
    from code_scalpel.fork import HumanForker


@dataclass
class _Streaks:
    """Consecutive-failure / consecutive-skip counters for the run loop.

    Skips are tracked separately from failures: a skip is almost always
    harmless — the 14b coder builds holistically (all commands in one
    notes.py across T002-T003), so later "implement list/delete" tasks
    become no-ops. Counting a skip as a failure lets max_failures abort the
    run before the suite goes green (observed: T004 skip + T005 fail = abort
    before a green suite). The skip threshold is softer — it only catches a
    total give-up (the model does nothing several tasks in a row).
    """

    skip_giveup_threshold: int
    failures: int = 0
    skips: int = 0

    def record(self, status: str, stop_after_failures: int) -> str | None:
        """Fold one task outcome into the streaks; return a stop reason or None."""
        if status == "done":
            self.failures = 0
            self.skips = 0
            return None
        if status == "failed":
            # A real failure (the model tried and broke something) — strict
            # threshold. A failure breaks the skip streak: there was activity.
            self.failures += 1
            self.skips = 0
            return "max_failures" if self.failures >= stop_after_failures else None
        # "skipped" — the model did not touch the workspace for this task.
        self.skips += 1
        return "task_not_done" if self.skips >= self.skip_giveup_threshold else None


def _last_not_done_index(tasks: list[Task]) -> int:
    """Index of the last not-done task, or -1 if every task is done.

    Pure plan structure — no LLM, no filesystem. Retained as a sensible
    fallback / informational signal; the enforcement position is now
    `_last_applicable_index` (see below).
    """
    last = -1
    for idx, task in enumerate(tasks):
        if not task.done:
            last = idx
    return last


def _last_applicable_index(tasks: list[Task], adapter: object | None) -> int:
    """Index of the last not-done task whose derived spec is APPLICABLE, or -1.

    The acceptance-gate position signal: `should_run_now` is `idx == this`.
    Enforcement fires at the last *applicable* task (the deliverable-complete
    point) rather than the literal last task — so a runnable-CLI deliverable
    built before a trailing test/doc task is still enforced (Gap B). Computed
    from the EXISTING pure per-task predicate `adapter.acceptance_applicable`
    (decodes the pre-loop written-back derived marker — no LLM, no I/O), so it
    is as cheap and deterministic as `_last_not_done_index`.

    Two no-regression invariants hold by construction: an early CLI-building
    task that is not the last applicable task is never the enforcing position
    (observed, never demoted); a plan with no applicable spec — a library, a
    non-CLI project, or no acceptance adapter — has no applicable index and
    returns the -1 sentinel → `should_run_now` is never True → never enforced.
    """
    applicable = getattr(adapter, "acceptance_applicable", None) if adapter is not None else None
    if applicable is None:
        return -1
    last = -1
    for idx, task in enumerate(tasks):
        if task.done:
            continue
        try:
            if applicable(task):
                last = idx
        except Exception:
            # A predicate raise must never break the loop — treat as not
            # applicable (observe), matching the adapter's own tolerance.
            continue
    return last


class PlanRunner:
    """Executes `.code-scalpel/TASKS.md` task-by-task on behalf of a StepAgent.

    See module docstring for the strangle rationale and the documented seam.
    """

    def __init__(self, agent: StepAgent) -> None:
        self._agent = agent
        # Stashes the most recent `code_with_retry` return so the build pass
        # and its classification/verification can share it across `_run_task`
        # and the self-fix attempts without re-threading it through args.
        self._last_step_result: StepResult | None = None

    async def run(
        self,
        *,
        stop_after_failures: int = 2,
        max_tasks: int | None = None,
        on_task_start: Callable[[Task], None] | None = None,
        on_task_end: Callable[[TaskOutcome], None] | None = None,
        on_tool_executed: Callable[[ToolCall, ToolResult], None] | None = None,
        context_limit: int | None = None,
        fork_resolver: HumanForker | None = None,
    ) -> RunPlanResult:
        """Walk `.code-scalpel/TASKS.md`, execute each non-done task through
        `code_with_retry`, and mark completed tasks `[✓]` atomically.

        Stop reasons: max_failures, plan_modified, all_done, no_tasks,
        max_tasks (see RunPlanResult). The `on_task_*` / `on_tool_executed`
        hooks let the TUI render progress; exceptions inside them are
        swallowed so a buggy widget cannot kill the loop.
        """
        from code_scalpel.agent import RunPlanResult
        from code_scalpel.plan_loading import load_plan

        loaded = await load_plan(self._agent, on_tool_executed, fork_resolver)
        if loaded is None:
            return RunPlanResult(outcomes=(), stopped_reason="no_tasks", tasks_completed=0)
        tasks, tasks_path, initial_hash = loaded
        if not tasks or all(t.done for t in tasks):
            reason = "no_tasks" if not tasks else "all_done"
            return RunPlanResult(outcomes=(), stopped_reason=reason, tasks_completed=0)

        return await self._run_loop(
            tasks=tasks,
            tasks_path=tasks_path,
            initial_hash=initial_hash,
            stop_after_failures=stop_after_failures,
            max_tasks=max_tasks,
            on_task_start=on_task_start,
            on_task_end=on_task_end,
            on_tool_executed=on_tool_executed,
            context_limit=context_limit,
        )

    async def _run_loop(
        self,
        *,
        tasks: tuple[Task, ...],
        tasks_path: Path,
        initial_hash: str,
        stop_after_failures: int,
        max_tasks: int | None,
        on_task_start: Callable[[Task], None] | None,
        on_task_end: Callable[[TaskOutcome], None] | None,
        on_tool_executed: Callable[[ToolCall, ToolResult], None] | None,
        context_limit: int | None,
    ) -> RunPlanResult:
        from code_scalpel.agent import RunPlanResult
        from code_scalpel.skills import acceptance_adapter

        outcomes: list[TaskOutcome] = []
        streaks = _Streaks(skip_giveup_threshold=stop_after_failures + 2)
        # Mutable so we can flip individual tasks done without rebuilding it.
        live_tasks: list[Task] = list(tasks)
        stopped_reason = "all_done"

        # Position signal for acceptance enforcement: the index of the last
        # not-done task whose derived spec is APPLICABLE, at loop start. Pure
        # plan structure + the pre-loop written-back derived marker — no LLM,
        # no I/O (the marker is intent from task text, stable on a greenfield
        # repo). Enforcement fires only at this one position (Gap B): the
        # last-applicable task is the deliverable-complete point, so a runnable
        # CLI built before a trailing test/doc task is still enforced, while an
        # early CLI task and a no-applicable-spec plan stay observational by
        # construction. The adapter (or None for non-python projects) supplies
        # the pure `acceptance_applicable` predicate, resolved once here.
        adapter = acceptance_adapter(self._agent._cwd)
        last_applicable_index = _last_applicable_index(live_tasks, adapter)

        for idx, task in enumerate(live_tasks):
            if task.done:
                continue

            current_text = await self._before_task(
                task, initial_hash, tasks_path, context_limit, on_task_start, on_tool_executed
            )
            if current_text is None:  # plan-modification sentinel changed
                stopped_reason = "plan_modified"
                break

            should_run_now = idx == last_applicable_index
            outcome = await self._run_task(task, should_run_now, on_tool_executed)

            outcomes.append(outcome)
            if on_task_end is not None:
                with suppress(Exception):
                    on_task_end(outcome)

            self._persist_task_end(task, outcome)
            await run_post_task_checks(self._agent, task, outcome, on_tool_executed)

            if outcome.status == "done":
                live_tasks[idx] = Task(id=task.id, title=task.title, body=task.body, done=True)
                initial_hash = self._mark_done(live_tasks, tasks_path, current_text)

            stop = streaks.record(outcome.status, stop_after_failures)
            if stop is not None:
                stopped_reason = stop
                break

            if max_tasks is not None and len(outcomes) >= max_tasks:
                stopped_reason = "max_tasks"
                break

        completed = sum(1 for o in outcomes if o.status == "done")
        return RunPlanResult(
            outcomes=tuple(outcomes),
            stopped_reason=stopped_reason,
            tasks_completed=completed,
        )

    async def _before_task(
        self,
        task: Task,
        initial_hash: str,
        tasks_path: Path,
        context_limit: int | None,
        on_task_start: Callable[[Task], None] | None,
        on_tool_executed: Callable[[ToolCall, ToolResult], None] | None,
    ) -> str | None:
        """Per-task preamble; returns the on-disk TASKS.md text, or None to stop.

        None means the plan-modification sentinel changed under us (the user
        edited TASKS.md mid-run) — the caller stops with "plan_modified".
        """
        from code_scalpel.agent import _hash_text

        agent = self._agent
        # Between-task auto-compact: long plans on a 14b coder drift past the
        # prompt budget around task 5-7. Only fires when the TUI passed a
        # known context_limit; no-op on the first task.
        await agent.maybe_auto_compact(context_limit, on_tool_executed)

        # Start-hook BEFORE the modification check so the TUI shows
        # "● Running T00N…" the moment we commit to attempting this task.
        if on_task_start is not None:
            with suppress(Exception):
                on_task_start(task)

        self._persist_task_start(task)

        # Plan-modification detection — re-read before each task; the user's
        # mid-run edits win the race, already-marked tasks stay on disk.
        current_text: str = tasks_path.read_text()
        if _hash_text(current_text) != initial_hash:
            return None
        return current_text

    def _persist_task_start(self, task: Task) -> None:
        # Persist task-start: if the process dies mid-task, resume
        # knows which task was in flight and can show «Continue
        # T00N / Restart» in the entry-card. step_phase="generating"
        # is the broadest stamp — finer phases (applying / testing)
        # live inside code_with_retry; we set them there in v0.12.5
        # PR-C when we wire the inner pipeline.
        agent = self._agent
        if agent._state is not None:
            with suppress(Exception):
                agent._state.current_task = task.id  # type: ignore[attr-defined]
                agent._state.step_phase = "generating"  # type: ignore[attr-defined]
            agent._persist_state()

    async def _run_task(
        self,
        task: Task,
        should_run_now: bool,
        on_tool_executed: Callable[[ToolCall, ToolResult], None] | None,
    ) -> TaskOutcome:
        """Dispatch one task and run the verification block.

        `should_run_now` is the position signal threaded into `verify_task`:
        True only on the last not-done task, where an applicable-intent
        deliverable should be runnable end-to-end (the acceptance gate
        enforces only there — earlier tasks observe).

        When the acceptance gate demotes the final task and trust permits, the
        bounded self-fix cycle (KD1) takes over before the demotion is final.
        """
        from code_scalpel.agent import _build_task_prompt, _classify_outcome

        prompt = _build_task_prompt(task)
        head_before = await self._build_task(task, prompt, on_tool_executed)
        step_result = self._last_step_result
        assert step_result is not None  # set by _build_task
        outcome = _classify_outcome(task, step_result)
        outcome = await verify_task(
            self._agent,
            task,
            outcome,
            head_before,
            on_tool_executed,
            should_run_now=should_run_now,
        )
        if not self._acceptance_demoted(outcome, should_run_now):
            return outcome
        return await self._self_fix_acceptance(task, outcome, prompt, on_tool_executed)

    async def _build_task(
        self,
        task: Task,
        prompt: str,
        on_tool_executed: Callable[[ToolCall, ToolResult], None] | None,
    ) -> str | None:
        """Snapshot HEAD, load skills, run one `code_with_retry` build pass.

        Returns the pre-build HEAD sha (None when `auto_git` is off) so the
        caller can re-evaluate the HEAD-advance check against THIS pass's
        commit — re-snapshotted per self-fix attempt, never carried stale.
        Stashes the build's `StepResult` on `self._last_step_result`.
        """
        agent = self._agent
        head_before: str | None = None
        if agent._config.agent.auto_git:
            head_before = await agent._git_head_sha()
        await agent._load_skills_for_task(task, on_tool_executed)
        self._last_step_result = await agent.code_with_retry(
            prompt,
            mode="code",
            on_tool_executed=on_tool_executed,
            force_loop=True,
            task_label=f"{task.id} — {task.title}",
        )
        return head_before

    def _acceptance_demoted(self, outcome: TaskOutcome, should_run_now: bool) -> bool:
        """True iff the acceptance gate (not checks 1-3) drove this demotion.

        The self-fix loop fires only on an acceptance demotion at the
        enforcing position: `verify_task` sets `acceptance_output` only when an
        applicable run-smoke FAILED, and `_demote` preserves it. A checks-1-3
        failure leaves `acceptance_output` None, so it is never self-fixed.
        """
        return (
            should_run_now
            and outcome.status == "failed"
            and outcome.acceptance_output is not None
            and self._agent._config.agent.acceptance_self_fix
        )

    async def _self_fix_acceptance(
        self,
        task: Task,
        outcome: TaskOutcome,
        prompt: str,
        on_tool_executed: Callable[[ToolCall, ToolResult], None] | None,
    ) -> TaskOutcome:
        """Bounded, trust-gated self-fix of an acceptance demotion (KD1).

        Re-feeds the failing run-smoke output to `code_with_retry`, rebuilds,
        and re-verifies up to the configured budget before the demotion is
        final. Trust is a machine check — `policy.auto_confirm` (skeptic never
        auto-fixes; KD3). One outer anti-loop guard: byte-identical run-smoke
        output two attempts in a row stops early (KD5). The retry prompt is
        assembled from the adapter-provided command + the run-smoke output
        only — zero language strings (KD9). A `code_with_retry` raise counts
        as a failed attempt (failure path 8); partial progress stays on disk.
        """
        from code_scalpel.agent import _classify_outcome
        from code_scalpel.policy import auto_confirm

        agent = self._agent
        if not auto_confirm(agent._config.agent.trust):
            # skeptic — fail immediately and wait for the human, as today (KD3).
            return outcome

        budget = agent._config.agent.acceptance_self_fix_max_attempts
        last_signal = outcome.acceptance_output
        for _ in range(budget):
            assert last_signal is not None  # _acceptance_demoted guarantees it
            retry_prompt = self._self_fix_prompt(prompt, last_signal)
            try:
                head_before = await self._build_task(task, retry_prompt, on_tool_executed)
            except Exception:
                # The rebuild engine raised — treat the attempt as failed, keep
                # partial progress on disk, and finalize `failed` (failure path 8).
                return outcome
            step_result = self._last_step_result
            assert step_result is not None  # set by _build_task
            retried = await verify_task(
                agent,
                task,
                _classify_outcome(task, step_result),
                head_before,
                on_tool_executed,
                should_run_now=True,
            )
            if retried.status == "done":
                return retried
            new_signal = retried.acceptance_output
            if new_signal is None or new_signal == last_signal:
                # Either the demotion was no longer acceptance-driven, or the
                # rebuild changed nothing observable — stop early (KD5).
                return retried
            outcome, last_signal = retried, new_signal
        return outcome

    @staticmethod
    def _self_fix_prompt(task_prompt: str, run_smoke_output: str) -> str:
        """Assemble the self-fix retry prompt from the task + run-smoke output.

        Target-language/tool agnostic (KD9): this method injects no
        target-language or tool literal (no `python`, `-m`, `notes_cli`, etc.).
        The command and the failure text both come from the `detect()`-selected
        adapter's run-smoke output, which already begins with the code-owned
        command line (the adapter's argv) and its stdout/stderr. The English
        instructional framing here is the deliberate, canon-compliant exception
        (artifacts are English) — it carries no target-language literal.
        """
        return (
            f"{task_prompt}\n\n"
            "The deliverable was built but its acceptance run did not pass. "
            "Fix the code so the run succeeds. The acceptance run produced:\n\n"
            f"{run_smoke_output}"
        )

    def _persist_task_end(self, task: Task, outcome: TaskOutcome) -> None:
        # Persist task-end: on success, mark the task done and clear
        # `current_task` so resume knows we finished and didn't crash
        # mid-flight. On failure / skip, keep `current_task` populated
        # — the entry-card will offer to retry it.
        agent = self._agent
        if agent._state is None:
            return
        with suppress(Exception):
            if outcome.status == "done":
                completed_ids = list(agent._state.completed_tasks)  # type: ignore[attr-defined]
                if task.id not in completed_ids:
                    completed_ids.append(task.id)
                    agent._state.completed_tasks = completed_ids  # type: ignore[attr-defined]
                agent._state.current_task = None  # type: ignore[attr-defined]
            agent._state.step_phase = "idle"  # type: ignore[attr-defined]
        agent._persist_state()

    def _mark_done(
        self,
        live_tasks: list[Task],
        tasks_path: Path,
        current_text: str,
    ) -> str:
        """Flip the task `[✓]` on disk and return the refreshed sentinel hash.

        Refreshes against OUR own write so the plan-modification check
        doesn't trip on the very change we just made.
        """
        from code_scalpel.agent import _atomic_write, _hash_text

        new_text = serialize_tasks(tuple(live_tasks), current_text)
        _atomic_write(tasks_path, new_text)
        return _hash_text(new_text)
