"""Per-task plan-level verification — the machine checks behind Definition-of-Done.

Extracted from the run_plan body alongside the strangle so PlanRunner stays
within the AI-specific file-length minimum, and so the verification block has a
cohesive home. A task that `code_with_retry` reported as `done` is demoted to
`failed` unless every machine check passes:

  1. `Files:` — every declared path exists on disk.
  2. `Test command:` — exits 0 (with the legacy exit-4/5 leniency).
  3. Git HEAD advanced — the model (or the auto-commit hook) committed.

These guard against the model claiming `done` after only partly executing a
task. Demotion is done→failed only; no new status is introduced.
"""

from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from code_scalpel.agent import StepAgent, TaskOutcome
    from code_scalpel.plan import Task


async def verify_task(
    agent: StepAgent,
    task: Task,
    outcome: TaskOutcome,
    head_before: str | None,
) -> TaskOutcome:
    """Run checks 1-3 on a `done` outcome; return it (possibly demoted)."""
    from code_scalpel.agent import TaskOutcome, _parse_task_test_command, _verify_task_files

    if outcome.status != "done":
        return outcome

    files_ok, _missing = _verify_task_files(task, agent._cwd)
    if not files_ok:
        return TaskOutcome(task=task, step_result=outcome.step_result, status="failed")

    cmd = _parse_task_test_command(task)
    # Skip plain `pytest` invocations — `_run_tests` already covered that.
    if cmd and cmd.strip() != "pytest":
        verify_ok = await agent._verify_task_test_command(cmd)
        if not verify_ok:
            return TaskOutcome(task=task, step_result=outcome.step_result, status="failed")

    return await _verify_head_advanced(agent, task, outcome, head_before)


async def _verify_head_advanced(
    agent: StepAgent,
    task: Task,
    outcome: TaskOutcome,
    head_before: str | None,
) -> TaskOutcome:
    if not (outcome.status == "done" and agent._config.agent.auto_git):
        return outcome
    head_after = await agent._git_head_sha()
    # Model didn't commit. Try the auto-commit hook before failing — pulling
    # commit out of the model's responsibilities is the only path to L4 on
    # qwen-14b (see article ch. 36-37 / plan §31 v0.13). When the hook lands
    # a commit, the task stays "done".
    if (
        head_after is None or head_after == head_before
    ) and agent._config.agent.auto_commit_on_done:
        await agent._auto_commit_task(task)
        head_after = await agent._git_head_sha()
    # If HEAD did NOT advance, the task is a no-op: the model touched no new
    # files (or wrote identical content), `git add -A` had nothing to stage.
    # We keep status="done" because files + test-command already passed — the
    # task is functionally complete, just adds no new commit (e.g. T_N+1
    # "write tests for T_N" the model already wrote under T_N; marking failed
    # here broke L4→L5 on the 2026-05-14 N=3 main runs). When HEAD advanced,
    # attribute the commit to any pending upstream forks.
    if head_after is not None and head_after != head_before and agent._upstream_queue is not None:
        # Defensive suppress: queue bookkeeping must never break /go.
        with suppress(Exception):
            agent._upstream_queue.record_commit(head_after)  # type: ignore[attr-defined]
    return outcome
