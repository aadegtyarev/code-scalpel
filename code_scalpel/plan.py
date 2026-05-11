"""Parse and serialise the planner's `.code-scalpel/TASKS.md`.

The planner writes a Markdown file with one `## T001: title` heading per
task plus a 5-line body. The supervised autonomous mode walks that file
top-to-bottom and needs two operations: read all tasks (with done-status
parsed from the heading), and rewrite one task's status without touching
anything else in the file — preamble, blank lines, trailing notes.

Status is encoded directly in the heading:
  - `## T001: title`         → not done
  - `## [✓] T001: title`     → done

The parser tolerates malformed headings (missing colon, missing body) —
those become empty/odd `Task` records rather than crash the run. The
agent is free to skip them or surface a warning; the file stays valid.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_HEADING_RE = re.compile(r"^##\s+(?:\[(?P<mark>.)\]\s+)?(?P<id>T\d{3,})\s*:?\s*(?P<title>.*)$")


@dataclass(frozen=True)
class Task:
    """One parsed entry from TASKS.md.

    `body` carries every line between this heading and the next heading
    (or EOF) verbatim — leading blank line included, trailing blanks
    stripped. The serialiser uses it as an opaque blob; we only ever
    rewrite the heading line itself, never the body.
    """

    id: str
    title: str
    body: str
    done: bool


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
