"""Optional per-task quality passes that run after a `done` task lands.

Extracted from the run_plan body alongside the strangle so PlanRunner stays
within the AI-specific file-length minimum. Every pass here is gated off by
default, runs only on a `done` outcome, surfaces findings as a synthetic
`on_tool_executed` card, and never fails the task. Behavior-preserving move
of the legacy `run_plan` quality block (`self.` → `agent.`).
"""

from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING

from code_scalpel.tools.agent_tools import ToolCall, ToolResult

if TYPE_CHECKING:
    from collections.abc import Callable

    from code_scalpel.agent import StepAgent, StepResult, TaskOutcome
    from code_scalpel.plan import Task


async def run_post_task_checks(
    agent: StepAgent,
    task: Task,
    outcome: TaskOutcome,
    on_tool_executed: Callable[[ToolCall, ToolResult], None] | None,
) -> None:
    """Dispatch the optional review / sanity / lint passes for a done task."""
    if outcome.status != "done":
        return
    step_result = outcome.step_result
    # A `done` outcome always carries its StepResult (only skip/stop leave it
    # None); the guard narrows the type for the checks below.
    if step_result is None:
        return

    cfg = agent._config.agent
    if cfg.per_step_review:
        await _per_step_review(agent, task, step_result, on_tool_executed)
    if cfg.test_sanity_pass:
        await _test_sanity(agent, step_result, on_tool_executed)
    if cfg.empty_test_detect:
        _empty_test(agent, step_result, on_tool_executed)
    if cfg.import_graph_check:
        _import_graph(agent, step_result, on_tool_executed)
    if cfg.lint_pass:
        await _lint(agent, step_result, on_tool_executed)


async def _per_step_review(
    agent: StepAgent,
    task: Task,
    step_result: StepResult,
    on_tool_executed: Callable[[ToolCall, ToolResult], None] | None,
) -> None:
    # Independent skeptic turn on the diff we just landed.
    with suppress(Exception):
        review = await agent.per_step_review(task, step_result)
        if review is not None and on_tool_executed is not None:
            call = ToolCall(name="per_step_review", body=task.id)
            with suppress(Exception):
                on_tool_executed(call, ToolResult(call, output=review.text, ok=True))


async def _test_sanity(
    agent: StepAgent,
    step_result: StepResult,
    on_tool_executed: Callable[[ToolCall, ToolResult], None] | None,
) -> None:
    from code_scalpel.agent import _test_paths_from_step_result

    # Independent judge on every modified test file.
    for test_path in _test_paths_from_step_result(step_result, agent._cwd):
        with suppress(Exception):
            verdict = await agent.judge_test_sanity(test_path)
            if verdict is not None and on_tool_executed is not None:
                call = ToolCall(name="test_sanity", body=str(test_path))
                with suppress(Exception):
                    on_tool_executed(call, ToolResult(call, output=verdict.text, ok=True))


def _empty_test(
    agent: StepAgent,
    step_result: StepResult,
    on_tool_executed: Callable[[ToolCall, ToolResult], None] | None,
) -> None:
    from code_scalpel.agent import _test_paths_from_step_result
    from code_scalpel.checks import detect_empty_tests

    # Deterministic AST detector — no LLM call.
    for test_path in _test_paths_from_step_result(step_result, agent._cwd):
        with suppress(Exception):
            empties = detect_empty_tests(test_path)
            if empties and on_tool_executed is not None:
                lines = [f"Empty / trivial tests in {test_path.name}:"]
                lines.extend(f"  - {e.name}: {e.reason}" for e in empties)
                call = ToolCall(name="empty_test", body=str(test_path))
                with suppress(Exception):
                    on_tool_executed(call, ToolResult(call, output="\n".join(lines), ok=False))


def _import_graph(
    agent: StepAgent,
    step_result: StepResult,
    on_tool_executed: Callable[[ToolCall, ToolResult], None] | None,
) -> None:
    from code_scalpel.agent import _py_paths_from_step_result
    from code_scalpel.checks import check_imports

    # Every in-project import in touched files must resolve to a real export.
    for py_path in _py_paths_from_step_result(step_result, agent._cwd):
        with suppress(Exception):
            issues = check_imports(py_path, agent._cwd)
            if issues and on_tool_executed is not None:
                lines = [f"Unresolved imports in {py_path.name}:"]
                lines.extend(
                    f"  - line {i.line}: from {i.module} import {i.name} ({i.reason})"
                    for i in issues
                )
                call = ToolCall(name="import_graph", body=str(py_path))
                with suppress(Exception):
                    on_tool_executed(call, ToolResult(call, output="\n".join(lines), ok=False))


async def _lint(
    agent: StepAgent,
    step_result: StepResult,
    on_tool_executed: Callable[[ToolCall, ToolResult], None] | None,
) -> None:
    from code_scalpel.agent import _py_paths_from_step_result
    from code_scalpel.checks import lint_paths

    # ruff/mypy on every changed .py file; skipped silently if neither on PATH.
    py_paths = _py_paths_from_step_result(step_result, agent._cwd)
    if not py_paths:
        return
    with suppress(Exception):
        reports = await lint_paths(
            py_paths,
            agent._cwd,
            timeout=agent._config.agent.lint_pass_timeout,
        )
        for r in reports:
            if r.findings and on_tool_executed is not None:
                call = ToolCall(name="lint_pass", body=str(r.path))
                with suppress(Exception):
                    on_tool_executed(call, ToolResult(call, output=r.findings, ok=False))
