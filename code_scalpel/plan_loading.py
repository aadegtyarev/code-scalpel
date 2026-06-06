"""Plan-loading helpers for PlanRunner — TASKS.{json,md} resolution + pre-loop passes.

Extracted from the run_plan body alongside the strangle (`PlanRunner`) so the
runner module stays within the AI-specific file-length minimum. These functions
own the *setup before the per-task loop*: resolving the live task list, keeping
the markdown sentinel in sync, ensuring the git repo, the one-shot skill
annotation pass, fork detection, and recipe learning — verbatim from the legacy
`run_plan` body (`self.` → `agent.`), behavior-preserving.
"""

from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING

from code_scalpel.plan import Task, parse_tasks_md
from code_scalpel.tools.agent_tools import ToolCall, ToolResult

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from code_scalpel.agent import StepAgent
    from code_scalpel.fork import HumanForker


async def load_plan(
    agent: StepAgent,
    on_tool_executed: Callable[[ToolCall, ToolResult], None] | None,
    fork_resolver: HumanForker | None,
) -> tuple[tuple[Task, ...], Path, str] | None:
    """Resolve TASKS.{json,md} into the live task list + sentinel hash.

    Returns `(tasks, tasks_path, initial_hash)`, or `None` when there is
    no plan file at all ("no_tasks"). Performs the pre-loop side effects
    (git repo ensure, skill annotation, fork detection, recipe learning)
    exactly as the legacy body did.
    """
    resolved = _resolve_task_list(agent)
    if resolved is None:
        return None
    tasks, tasks_path, original_text, initial_hash = resolved
    if not tasks or all(t.done for t in tasks):
        return tasks, tasks_path, initial_hash

    return await _pre_loop_passes(
        agent, tasks, tasks_path, original_text, initial_hash, on_tool_executed, fork_resolver
    )


def _resolve_task_list(
    agent: StepAgent,
) -> tuple[tuple[Task, ...], Path, str, str] | None:
    """Read TASKS.{json,md} into `(tasks, tasks_path, original_text, hash)`.

    None when no plan file exists at all. JSON is the source of truth when
    present; the markdown is re-rendered to stay the on-disk plan-modification
    sentinel (hash-compared each iteration), so a user hand-edit mid-run is
    still detected. Write the markdown only when it differs (mtime hygiene).
    """
    from code_scalpel.agent import _hash_text
    from code_scalpel.plan import parse_tasks_json, render_tasks_markdown

    json_path = agent._cwd / ".code-scalpel" / "TASKS.json"
    tasks_path = agent._cwd / ".code-scalpel" / "TASKS.md"
    tasks: tuple[Task, ...] = ()
    if json_path.is_file():
        tasks = parse_tasks_json(json_path.read_text())
        rendered = render_tasks_markdown(tasks) if tasks else ""
        if rendered and (not tasks_path.is_file() or tasks_path.read_text() != rendered):
            tasks_path.parent.mkdir(parents=True, exist_ok=True)
            tasks_path.write_text(rendered)
    if not tasks_path.is_file():
        return None

    original_text = tasks_path.read_text()
    if not tasks:
        tasks = parse_tasks_md(original_text)
    return tasks, tasks_path, original_text, _hash_text(original_text)


async def _pre_loop_passes(
    agent: StepAgent,
    tasks: tuple[Task, ...],
    tasks_path: Path,
    original_text: str,
    initial_hash: str,
    on_tool_executed: Callable[[ToolCall, ToolResult], None] | None,
    fork_resolver: HumanForker | None,
) -> tuple[tuple[Task, ...], Path, str]:
    """The one-time setup before the per-task loop: git repo, skill
    annotation, fork detection, recipe learning. Returns the (possibly
    updated) `(tasks, tasks_path, initial_hash)`.
    """
    from code_scalpel.agent import _hash_text, _parse_task_skills

    # Ensure a git repo exists BEFORE the loop so every task can land in its
    # own commit. Gated on auto_git so hermetic callers stay side-effect-free.
    if agent._config.agent.auto_git:
        await agent._ensure_git_repo()

    # If the plan has no `Skills:` annotations, fire one LLM pass to add them
    # and write the decision back so the user (and the next run) sees it.
    if agent._config.agent.auto_annotate_plan and not any(_parse_task_skills(t) for t in tasks):
        original_text, initial_hash, tasks = await _annotate_plan(
            agent, tasks_path, original_text, on_tool_executed
        )

    # Detect + resolve architectural forks before the first task. Gated on a
    # resolver actually being wired (no resolver → headless run, nothing to do).
    if (
        agent._config.agent.auto_detect_forks
        and fork_resolver is not None
        and "## Architectural decisions" not in original_text
    ):
        await agent._detect_and_resolve_forks(
            tasks_path=tasks_path,
            original_text=original_text,
            fork_resolver=fork_resolver,
            on_tool_executed=on_tool_executed,
        )
        # Re-read — we just rewrote the file with the decisions block.
        original_text = tasks_path.read_text()
        initial_hash = _hash_text(original_text)

    # Auto-learn a local recipe for each skill that lacks one. Best-effort —
    # a network failure silently skips that skill rather than aborting.
    if agent._config.agent.auto_annotate_plan:
        await agent._auto_learn_missing_recipes(tasks, on_tool_executed)

    return tasks, tasks_path, initial_hash


async def _annotate_plan(
    agent: StepAgent,
    tasks_path: Path,
    original_text: str,
    on_tool_executed: Callable[[ToolCall, ToolResult], None] | None,
) -> tuple[str, str, tuple[Task, ...]]:
    """Run the one-shot skill-annotation LLM pass and persist its result.

    Returns the (possibly updated) `(original_text, initial_hash, tasks)`.
    """
    from code_scalpel.agent import _atomic_write, _hash_text, _parse_task_skills

    # Surface the pass — an extra LLM call before the loop; running it
    # silently would look like the agent froze.
    _emit_annotate_card(on_tool_executed, "Annotating plan with skills (1 LLM pass)…", ok=True)
    new_text = await agent._annotate_plan_with_skills(original_text)
    if new_text and new_text != original_text:
        _atomic_write(tasks_path, new_text)
        tasks = parse_tasks_md(new_text)
        # Surface what got picked, per task — one line each so the user
        # can scan it without reopening TASKS.md.
        lines = ["Plan annotated. Skills per task:"]
        for t in tasks:
            s = _parse_task_skills(t)
            lines.append(f"  {t.id}: {', '.join(s) if s else 'none'}")
        _emit_annotate_card(on_tool_executed, "\n".join(lines), ok=True)
        return new_text, _hash_text(new_text), tasks
    _emit_annotate_card(
        on_tool_executed,
        "Annotation pass returned no changes — running plan without auto-loaded skills.",
        ok=False,
    )
    return original_text, _hash_text(original_text), parse_tasks_md(original_text)


def _emit_annotate_card(
    on_tool_executed: Callable[[ToolCall, ToolResult], None] | None,
    output: str,
    *,
    ok: bool,
) -> None:
    if on_tool_executed is None:
        return
    call = ToolCall(name="annotate_plan", body="{}")
    with suppress(Exception):
        on_tool_executed(call, ToolResult(call, output=output, ok=ok))
