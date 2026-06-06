"""Per-task plan-level verification — the machine checks behind Definition-of-Done.

Extracted from the run_plan body alongside the strangle so PlanRunner stays
within the AI-specific file-length minimum, and so the verification block has a
cohesive home. A task that `code_with_retry` reported as `done` is demoted to
`failed` unless every machine check passes:

  1. `Files:` — every declared path exists on disk.
  2. `Test command:` — exits 0 (with the legacy exit-4/5 leniency).
  3. Git HEAD advanced — the model (or the auto-commit hook) committed.
  4. Acceptance run-smoke — when an acceptance adapter resolves for the
     project root, run the deliverable as a user would (`python -m <pkg>
     --help`) and demote unless it exits 0 (exit-0-or-fail; NO exit-4/5
     leniency — a finished deliverable has no test-ordering excuse).

These guard against the model claiming `done` after only partly executing a
task. Demotion is done→failed only; no new status is introduced. The
acceptance run-smoke command/verdict/reason are persisted to AgentState.
"""

from __future__ import annotations

import json
import shlex
from contextlib import suppress
from typing import TYPE_CHECKING

from code_scalpel.skills import acceptance_adapter
from code_scalpel.tools.agent_tools import ToolCall, ToolResult, execute

if TYPE_CHECKING:
    from collections.abc import Callable

    from code_scalpel.agent import StepAgent, TaskOutcome
    from code_scalpel.plan import Task

    OnToolExecuted = Callable[[ToolCall, ToolResult], None] | None


async def verify_task(
    agent: StepAgent,
    task: Task,
    outcome: TaskOutcome,
    head_before: str | None,
    on_tool_executed: OnToolExecuted = None,
) -> TaskOutcome:
    """Run checks 1-4 on a `done` outcome; return it (possibly demoted)."""
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

    outcome = await _verify_head_advanced(agent, task, outcome, head_before)
    return await _verify_acceptance(agent, task, outcome, on_tool_executed)


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


async def _verify_acceptance(
    agent: StepAgent,
    task: Task,
    outcome: TaskOutcome,
    on_tool_executed: OnToolExecuted = None,
) -> TaskOutcome:
    """Verification #4 — run the deliverable as a user would.

    When `acceptance_adapter(root)` resolves (a python-cli project today),
    run the adapter's run-smoke (`python -m <pkg> --help`); a still-`done`
    task is demoted to `failed` unless run-smoke exits 0. No acceptance
    adapter → a logged no-op, the verdict from checks 1-3 stands (no
    regression for unsupported types). Mandatory-when-resolves: the gate
    cannot be silently skipped for a type the floor covers.
    """
    from code_scalpel.agent import TaskOutcome

    if outcome.status != "done":
        return outcome

    adapter = acceptance_adapter(agent._cwd)
    if adapter is None:
        # No acceptance adapter for this project type — logged no-op.
        _record_acceptance(agent, command=None, verdict="noop", reason=None)
        _emit_acceptance_card(on_tool_executed, command=None, ok=True, reason="no adapter")
        return outcome

    passed, command, reason = await _run_smoke(agent, adapter, task)
    if passed:
        _record_acceptance(agent, command=command, verdict="passed", reason=None)
        _emit_acceptance_card(on_tool_executed, command=command, ok=True, reason=None)
        return outcome
    _record_acceptance(agent, command=command, verdict="failed", reason=reason)
    _emit_acceptance_card(on_tool_executed, command=command, ok=False, reason=reason)
    return TaskOutcome(task=task, step_result=outcome.step_result, status="failed")


def _emit_acceptance_card(
    on_tool_executed: OnToolExecuted,
    *,
    command: str | None,
    ok: bool,
    reason: str | None,
) -> None:
    """Surface the acceptance step via the existing on_tool_executed card seam.

    Rides the same synthetic-card pattern the per-step-review / annotation
    passes use, so the user sees the run-smoke command + ✓/✗ (and the no-op
    for unsupported types) without any structural TUI change.
    """
    if on_tool_executed is None:
        return
    if command is None:
        output = f"Acceptance run-smoke skipped ({reason})."
    elif ok:
        output = f"Acceptance run-smoke passed: {command}"
    else:
        output = f"Acceptance run-smoke failed ({reason}): {command}"
    call = ToolCall(name="acceptance", body=command or "")
    with suppress(Exception):
        on_tool_executed(call, ToolResult(call, output=output, ok=ok))


async def _run_smoke(
    agent: StepAgent,
    adapter: object,
    task: Task,
) -> tuple[bool, str | None, str | None]:
    """Execute the adapter's acceptance run-smoke; return (passed, command, reason).

    Runs the code-owned acceptance command at trust="yolo" through the same
    `execute()` boundary (so it inherits trust / policy / bwrap gating;
    timeout + sandbox from config — no magic number). Exit-0-or-fail: unlike
    `_verify_task_test_command` there is no exit-4/5 leniency. `resolve_pkg`
    raising → `pkg-unresolvable`, the failure the gate exists to catch.
    """
    try:
        spec = adapter.acceptance_spec(task)  # type: ignore[attr-defined]
    except ValueError:
        # `resolve_pkg` could not resolve a runnable package — "not runnable"
        # is exactly the failure the gate catches (the __main__.py coin-flip).
        return False, None, "pkg-unresolvable"
    if spec is None:
        # An adapter that flags provides_acceptance but returns no spec — treat
        # as a no-op rather than crashing; nothing runnable to verify.
        return True, None, None

    # The command is the adapter's code-owned acceptance command (deterministic
    # `python -m <pkg> --help`, pkg resolved by resolve_pkg — never model- or
    # user-authored). Re-derive the argv to prove no shell metacharacters/
    # free-form text reach the shell, then rebuild the string from that argv.
    # asyncio-subprocess security considerations: never pass untrusted input to
    # a shell.
    # https://docs.python.org/3/library/asyncio-subprocess.html#security-considerations
    raw_command, _expected = spec
    command = shlex.join(shlex.split(raw_command))
    call = ToolCall(name="shell_exec", body=json.dumps({"command": command}))
    result = await execute(
        call,
        agent._cwd,
        max_lines=agent._config.agent.max_file_lines,
        runner=agent._shell_runner,
        trust="yolo",
        shell_exec_timeout=agent._config.agent.shell_exec_timeout,
        sandbox=agent._config.agent.sandbox,
    )
    if result.ok:
        return True, command, None
    return False, command, _failure_reason(result)


def _failure_reason(result: ToolResult) -> str:
    """Map a failed run-smoke ToolResult to a compact reason string."""
    out = result.output.lower()
    if "timeout" in out:
        return "timeout"
    for line in result.output.splitlines():
        stripped = line.strip().lower()
        if stripped.startswith("exit code:"):
            return f"exit {stripped.removeprefix('exit code:').strip().split()[0]}"
    return "run-smoke failed"


def _record_acceptance(
    agent: StepAgent,
    *,
    command: str | None,
    verdict: str,
    reason: str | None,
) -> None:
    """Persist the last run-smoke command + verdict + reason to AgentState.

    Defensive suppress + the existing atomic save — acceptance bookkeeping
    must never break /go. No-op when no state is wired.
    """
    if agent._state is None:
        return
    with suppress(Exception):
        agent._state.last_acceptance_command = command  # type: ignore[attr-defined]
        agent._state.last_acceptance_verdict = verdict  # type: ignore[attr-defined]
        agent._state.last_acceptance_reason = reason  # type: ignore[attr-defined]
    agent._persist_state()
