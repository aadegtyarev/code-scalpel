"""Parse and serialise the planner's task list.

Two parallel formats live on disk during the v0.14 migration:

- `.code-scalpel/TASKS.json` — canonical machine-readable format.
  Produced by the planner via `response_format=json_schema` so each
  field arrives typed (no markdown variants, no quote-stripping
  heuristics). Read first by the runtime.

- `.code-scalpel/TASKS.md` — derived view, rendered from the JSON
  for human eyes (TUI inline preview, `cat TASKS.md` in a terminal,
  manual edits). When the user hand-edits TASKS.md, we re-parse it
  back through the legacy markdown path on next read.

Status is encoded directly in the heading of the markdown view:
  - `## T001: title`         → not done
  - `## [✓] T001: title`     → done

The markdown parser tolerates malformed headings — those become
empty/odd `Task` records rather than crash the run.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

_HEADING_RE = re.compile(r"^##\s+(?:\[(?P<mark>.)\]\s+)?(?P<id>T\d{3,})\s*:?\s*(?P<title>.*)$")


@dataclass(frozen=True)
class Task:
    """One task entry.

    Typed fields (`goal` / `files` / `acceptance` / `skills` /
    `test_command`) are filled by the JSON-schema path. Legacy
    markdown-parsed tasks leave them empty and store everything in
    `body` for back-compat — old code accesses via the body-blob
    parsers in agent.py. New code should reach for the typed fields.

    `body` carries every line between this heading and the next heading
    (or EOF) verbatim — leading blank line included, trailing blanks
    stripped. The serialiser uses it as an opaque blob; we only ever
    rewrite the heading line itself, never the body.
    """

    id: str
    title: str
    body: str
    done: bool
    # v0.14 typed fields. Empty when task came from legacy markdown
    # without JSON sidecar. `test_command=None` is the sentinel for
    # "no machine verification needed" (manual / n/a / etc).
    goal: str = ""
    files: tuple[str, ...] = field(default_factory=tuple)
    acceptance: tuple[str, ...] = field(default_factory=tuple)
    skills: tuple[str, ...] = field(default_factory=tuple)
    test_command: str | None = None


def parse_tasks_md(text: str) -> tuple[Task, ...]:
    """Split a TASKS.md file into tasks. Returns an empty tuple for an
    empty file or a file without any `## T###:` headings."""
    if not text.strip():
        return ()
    lines = text.splitlines(keepends=True)
    headings: list[tuple[int, re.Match[str]]] = []
    for idx, line in enumerate(lines):
        m = _HEADING_RE.match(line.rstrip("\n"))
        if m is None:
            continue
        headings.append((idx, m))

    if not headings:
        return ()

    tasks: list[Task] = []
    for i, (line_idx, m) in enumerate(headings):
        end = headings[i + 1][0] if i + 1 < len(headings) else len(lines)
        body = "".join(lines[line_idx + 1 : end]).rstrip("\n")
        mark = (m.group("mark") or "").strip()
        done = mark in ("✓", "x", "X")
        tasks.append(
            Task(
                id=m.group("id"),
                title=m.group("title").strip(),
                body=body,
                done=done,
            )
        )
    return tuple(tasks)


def _format_heading(task: Task) -> str:
    if task.done:
        return f"## [✓] {task.id}: {task.title}".rstrip()
    return f"## {task.id}: {task.title}".rstrip()


def serialize_tasks(tasks: tuple[Task, ...], original_text: str) -> str:
    """Produce a TASKS.md preserving every non-heading character of
    `original_text` and updating only the heading lines whose Task
    status changed.

    Bodies come from `original_text`, not from `tasks[i].body` — that
    way a caller who hand-edits a Task's body never accidentally
    overwrites the on-disk version through this path. The status flip
    is the ONLY thing that lands.
    """
    if not tasks:
        return original_text

    lines = original_text.splitlines(keepends=True)
    task_by_id = {t.id: t for t in tasks}
    out: list[str] = []
    for line in lines:
        m = _HEADING_RE.match(line.rstrip("\n"))
        if m is None:
            out.append(line)
            continue
        task = task_by_id.get(m.group("id"))
        if task is None:
            out.append(line)
            continue
        # Preserve the original line ending so we don't accidentally
        # convert CRLF → LF or strip the final newline.
        ending = line[len(line.rstrip("\r\n")) :]
        out.append(_format_heading(task) + ending)
    return "".join(out)


# JSON schema for `response_format=json_schema` — drives the planner
# to emit typed JSON instead of free-form markdown DSL. Field shape
# mirrors the typed Task dataclass above. v0.14 step 1.
PLAN_JSON_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "tasks": {
            "type": "array",
            "minItems": 1,
            "maxItems": 9,
            "items": {
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "pattern": "^T\\d{3}$",
                        "description": "Task identifier T001..T009 in plan order.",
                    },
                    "title": {
                        "type": "string",
                        "description": "Short imperative title.",
                    },
                    "goal": {
                        "type": "string",
                        "description": "One-line description of the outcome.",
                    },
                    "files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Project files this task creates or modifies. "
                            "Only the paths this task itself touches — "
                            "files created by later tasks belong to those "
                            "tasks. Real paths from the project map; for "
                            "new files, the path you'll create."
                        ),
                    },
                    "acceptance": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Observable test or behaviour bullets.",
                    },
                    "skills": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Skill names (e.g. python). Empty if irrelevant.",
                    },
                    "test_command": {
                        "type": ["string", "null"],
                        "description": (
                            "Exact shell command that proves the task done "
                            "(e.g. `pytest tests/test_x.py`). Null when "
                            "verification is manual or N/A — do NOT write "
                            "the string 'manual' here, use null."
                        ),
                    },
                },
                "required": [
                    "id",
                    "title",
                    "goal",
                    "files",
                    "acceptance",
                    "test_command",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["tasks"],
    "additionalProperties": False,
}


def task_from_json(d: dict[str, Any]) -> Task:
    """Build a Task from one schema-validated dict. Caller already ran
    the response through `response_format=json_schema`, so we don't
    re-validate shape — only normalise."""
    files_in = d.get("files") or []
    acceptance_in = d.get("acceptance") or []
    skills_in = d.get("skills") or []
    test_cmd_raw = d.get("test_command")
    test_cmd: str | None
    test_cmd = str(test_cmd_raw) if test_cmd_raw else None
    return Task(
        id=str(d["id"]),
        title=str(d["title"]).strip(),
        body="",  # JSON path leaves body empty; typed fields are source of truth
        done=False,
        goal=str(d.get("goal", "")).strip(),
        files=tuple(str(x) for x in files_in),
        acceptance=tuple(str(x).strip() for x in acceptance_in),
        skills=tuple(str(x).strip() for x in skills_in),
        test_command=test_cmd,
    )


def parse_tasks_json(text: str) -> tuple[Task, ...]:
    """Parse `.code-scalpel/TASKS.json` produced by the JSON planner.

    Returns an empty tuple for unparseable or empty files (mirrors
    `parse_tasks_md` behaviour). Caller decides whether to fall back
    to markdown or treat as "no plan".

    `done` flag for JSON tasks lives in a sibling `completed` list at
    the top level so the schema for incoming model output stays minimal
    (model never has to fill `done` — that's runtime state)."""
    if not text.strip():
        return ()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return ()
    if not isinstance(data, dict):
        return ()
    raw_tasks = data.get("tasks") or ()
    if not isinstance(raw_tasks, list):
        return ()
    completed_ids = set(data.get("completed", ()))
    out: list[Task] = []
    for raw in raw_tasks:
        if not isinstance(raw, dict):
            continue
        task = task_from_json(raw)
        if task.id in completed_ids:
            task = Task(
                id=task.id,
                title=task.title,
                body=task.body,
                done=True,
                goal=task.goal,
                files=task.files,
                acceptance=task.acceptance,
                skills=task.skills,
                test_command=task.test_command,
            )
        out.append(task)
    return tuple(out)


def serialize_tasks_json(tasks: tuple[Task, ...]) -> str:
    """Render tasks to canonical JSON for `.code-scalpel/TASKS.json`.

    Done-status lives in a sibling `completed` list, not on each task,
    so the model-emitted schema (which never has to fill done) stays
    one-to-one with what gets stored."""
    payload = {
        "tasks": [
            {
                "id": t.id,
                "title": t.title,
                "goal": t.goal,
                "files": list(t.files),
                "acceptance": list(t.acceptance),
                "skills": list(t.skills),
                "test_command": t.test_command,
            }
            for t in tasks
        ],
        "completed": [t.id for t in tasks if t.done],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def render_tasks_markdown(tasks: tuple[Task, ...]) -> str:
    """Render typed tasks back to the legacy markdown DSL.

    Used as a human-readable view (TUI inline preview, `cat TASKS.md`).
    Round-trip not guaranteed: model-emitted Test command is wrapped in
    backticks for readability, comments / quotes are stripped, fields
    appear in canonical order. The JSON file is the source of truth.
    """
    out: list[str] = []
    for t in tasks:
        head = "## " + ("[✓] " if t.done else "") + f"{t.id}: {t.title}"
        out.append(head)
        out.append("")
        if t.goal:
            out.append(f"Goal: {t.goal}")
        if t.files:
            out.append("Files: " + ", ".join(t.files))
        if t.skills:
            out.append("Skills: " + ", ".join(t.skills))
        if t.acceptance:
            out.append("Acceptance:")
            for bullet in t.acceptance:
                out.append(f"- {bullet}")
        if t.test_command is None:
            out.append("Test command: manual")
        else:
            out.append(f"Test command: `{t.test_command}`")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


__all__ = [
    "PLAN_JSON_SCHEMA",
    "Task",
    "parse_tasks_json",
    "parse_tasks_md",
    "render_tasks_markdown",
    "serialize_tasks",
    "serialize_tasks_json",
    "task_from_json",
]
