"""Plan-loading helpers for PlanRunner — TASKS.{json,md} resolution + pre-loop passes.

Extracted from the run_plan body alongside the strangle (`PlanRunner`) so the
runner module stays within the AI-specific file-length minimum. These functions
own the *setup before the per-task loop*: resolving the live task list, keeping
the markdown sentinel in sync, ensuring the git repo, the one-shot skill
annotation pass, fork detection, and recipe learning — verbatim from the legacy
`run_plan` body (`self.` → `agent.`), behavior-preserving.
"""

from __future__ import annotations

import dataclasses
from contextlib import suppress
from typing import TYPE_CHECKING

from code_scalpel.plan import Task, parse_tasks_md
from code_scalpel.skills import acceptance_adapter
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
            agent, tasks_path, original_text, tasks, on_tool_executed
        )

    # Derive an args-only acceptance spec for each task that declares none AND
    # whose project has an acceptance adapter, then write it back so the next
    # run is deterministic (KD5). Composes with the annotation pass above: each
    # re-hashes after its own write, neither clobbers the other.
    if agent._config.agent.auto_derive_acceptance and acceptance_adapter(agent._cwd) is not None:
        original_text, initial_hash, tasks = await _derive_acceptance(
            agent, tasks_path, original_text, tasks, on_tool_executed
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
    tasks: tuple[Task, ...],
    on_tool_executed: Callable[[ToolCall, ToolResult], None] | None,
) -> tuple[str, str, tuple[Task, ...]]:
    """Run the one-shot skill-annotation LLM pass and persist its result.

    Returns the (possibly updated) `(original_text, initial_hash, tasks)`.
    BOTH the change-path and the no-change path preserve the typed `Task`
    fields (goal/files/acceptance/skills/test_command): the LLM-added skills
    are merged BACK INTO the typed tasks tuple, never re-parsed from markdown.
    Re-parsing the annotated markdown via `parse_tasks_md` would strip every
    typed field to its empty default when the plan came from TASKS.json
    (finding 1 / finding 7) — and the acceptance-derivation pre-pass that runs
    next would then derive from a field-stripped task and persist the emptied
    plan back to disk, corrupting the user's typed plan.
    """
    from code_scalpel.agent import _atomic_write, _hash_text, _parse_task_skills

    # Surface the pass — an extra LLM call before the loop; running it
    # silently would look like the agent froze.
    _emit_annotate_card(on_tool_executed, "Annotating plan with skills (1 LLM pass)…", ok=True)
    new_text = await agent._annotate_plan_with_skills(original_text)
    if new_text and new_text != original_text:
        _atomic_write(tasks_path, new_text)
        tasks = _merge_annotated_skills(tasks, new_text)
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
    return original_text, _hash_text(original_text), tasks


def _merge_annotated_skills(
    typed_tasks: tuple[Task, ...],
    annotated_text: str,
) -> tuple[Task, ...]:
    """Merge the LLM-added `Skills:` annotations back into the typed tasks.

    The annotation pass rewrites markdown; re-parsing it would drop every
    typed `Task` field (the plan came from TASKS.json). Instead, parse only
    to read each task's annotated `body` + skills, then carry those onto the
    matching typed task (by id) while preserving goal/files/acceptance/
    test_command. `_parse_task_skills` reads from `body`, so the body is the
    field that must carry the annotation; the typed `skills` field is updated
    in lockstep so both views agree. A typed task the annotation pass dropped
    (no matching heading) is kept unchanged.
    """
    from code_scalpel.agent import _parse_task_skills

    annotated_by_id = {t.id: t for t in parse_tasks_md(annotated_text)}
    merged: list[Task] = []
    for task in typed_tasks:
        ann = annotated_by_id.get(task.id)
        if ann is None:
            merged.append(task)
            continue
        merged.append(
            dataclasses.replace(
                task,
                body=ann.body,
                skills=tuple(_parse_task_skills(ann)),
            )
        )
    return tuple(merged)


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


async def _derive_acceptance(
    agent: StepAgent,
    tasks_path: Path,
    original_text: str,
    tasks: tuple[Task, ...],
    on_tool_executed: Callable[[ToolCall, ToolResult], None] | None,
) -> tuple[str, str, tuple[Task, ...]]:
    """Derive an args-only acceptance spec for each task lacking one, write back.

    Returns the (possibly updated) `(original_text, initial_hash, tasks)`. The
    write-back targets the JSON-canonical representation (round-trips via
    `task_from_json`) and the typed `tasks` tuple is returned directly — never
    re-parsed from markdown, which drops typed fields (finding 7). The markdown
    sentinel is re-rendered + re-hashed so the loop sees its OWN write, not a
    user mid-run edit. A failed derivation leaves the task untouched (falls
    back to the observational floor — failure-path 9); a write-back disk error
    keeps the in-memory derived tasks for this run (failure-path 10).
    """
    from code_scalpel.agent import _hash_text

    _emit_annotate_card(on_tool_executed, "Deriving acceptance specs (1 LLM pass/task)…", ok=True)
    new_tasks, lines, errors = await _derive_specs_for_tasks(agent, tasks)
    # A WHOLESALE outage (every derivation attempt errored — e.g. the LLM is
    # down) must not read as "no CLI here": surface it distinctly so silent
    # floor-everywhere is visible (review finding 7).
    if errors and new_tasks == tasks:
        _emit_annotate_card(
            on_tool_executed,
            f"Acceptance derivation FAILED for all {errors} task(s) (LLM error?) — "
            "tasks fall back to the observational floor; rerun to derive.",
            ok=False,
        )
        return original_text, _hash_text(original_text), tasks
    if new_tasks == tasks:
        _emit_annotate_card(
            on_tool_executed, "Acceptance derivation added no enforceable specs.", ok=True
        )
        return original_text, _hash_text(original_text), tasks

    new_text, persisted = _persist_derived_tasks(tasks_path, new_tasks)
    _emit_annotate_card(on_tool_executed, "\n".join(["Acceptance specs derived:", *lines]), ok=True)
    # When the write-back failed (disk error), the new tasks are used in-memory
    # this run but the on-disk sentinel is unchanged — return the OLD hash so
    # the loop matches disk and does NOT stop with `plan_modified` (failure-
    # path 10); the next run re-derives.
    sentinel = _hash_text(new_text) if persisted else _hash_text(original_text)
    return new_text, sentinel, new_tasks


async def _derive_specs_for_tasks(
    agent: StepAgent,
    tasks: tuple[Task, ...],
) -> tuple[tuple[Task, ...], list[str], int]:
    """Run the derivation per task lacking usable acceptance.

    Returns `(new_tasks, card_lines, error_count)`. A task is derived when it
    carries no usable acceptance — empty OR only malformed derived markers
    (review finding 4: a corrupt marker is treated as absent so it self-heals,
    never wedges the task). A human-declared (B) prose bullet does NOT block
    derivation: it is passed to the model as an intent HINT and the EXECUTED
    spec is always the derived (C) or floor (A) one — human prose is never
    run as argv (review finding 2). A None derivation (LLM/parse error) leaves
    the task unchanged so it falls back to the observational floor and is
    counted as an error for the outage signal (review finding 7).
    """
    from code_scalpel.skills.base import (
        acceptance_needs_derivation,
        decode_derived_acceptance,
        encode_derived_acceptance,
        is_marker_prefixed,
    )

    out: list[Task] = []
    lines: list[str] = []
    errors = 0
    for task in tasks:
        bullets = tuple(task.acceptance)
        if not acceptance_needs_derivation(bullets):
            out.append(task)
            continue
        hint = _human_acceptance_hint(bullets, decode_derived_acceptance, is_marker_prefixed)
        data = await agent.derive_acceptance_args(task, hint=hint)
        if data is None:
            errors += 1
            out.append(task)
            continue
        applicable = bool(data.get("applicable", False))
        args = str(data.get("args", ""))
        expected = str(data.get("expected", ""))
        marker = encode_derived_acceptance(applicable=applicable, args=args, expected=expected)
        # Replace the whole acceptance tuple with the single derived marker:
        # any prior prose (now consumed as a hint) or malformed marker is
        # superseded by the canonical derived spec.
        out.append(dataclasses.replace(task, acceptance=(marker,)))
        verdict = "enforced" if applicable else "observed (no runnable CLI)"
        lines.append(f"  {task.id}: {verdict}")
    return tuple(out), lines, errors


def _human_acceptance_hint(
    bullets: tuple[str, ...],
    decode: Callable[[str], dict[str, object] | None],
    is_marker: Callable[[str], bool],
) -> str:
    """Join the task's human-declared prose bullets into a derivation hint.

    Excludes derived markers (decodable or malformed) — only genuine
    human-written prose is intent the model should translate. Empty string
    when the task has no human prose.
    """
    prose = [b.strip() for b in bullets if b.strip() and decode(b) is None and not is_marker(b)]
    return "; ".join(prose)


def _persist_derived_tasks(tasks_path: Path, new_tasks: tuple[Task, ...]) -> tuple[str, bool]:
    """Write derived tasks to TASKS.json (canonical) + re-render the markdown
    sentinel; return (new_markdown_text, persisted). A disk error is swallowed
    so the derived tasks are still used in-memory this run (failure-path 10);
    `persisted=False` then tells the caller to keep the on-disk sentinel.
    """
    from code_scalpel.agent import _atomic_write
    from code_scalpel.plan import render_tasks_markdown, serialize_tasks_json

    new_text = render_tasks_markdown(new_tasks)
    try:
        json_path = tasks_path.parent / "TASKS.json"
        _atomic_write(json_path, serialize_tasks_json(new_tasks))
        _atomic_write(tasks_path, new_text)
    except OSError:
        return new_text, False
    return new_text, True
