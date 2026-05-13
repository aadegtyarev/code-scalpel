"""Inline card for the planner's TASKS.md artefact.

Planner mode (`/mode plan` or Ctrl+T → plan) ends a turn by writing
`.code-scalpel/TASKS.md` — a small structured breakdown the user is then
meant to execute task-by-task. That file is the main output of the turn,
so this card defaults to **expanded** (compare ToolUseCard, which defaults
to collapsed: tool calls are side-info).

The card:
- Header: `📋 Plan (N tasks)` where N counts `## T###:` headings.
- Body: per-task block with bold title, dim files line, acceptance
  bullets, dim italic test command.

Markup safety: titles, file lists, acceptance items and test commands
all originate from the LLM and may contain `[`, `]`, `=` etc. that Rich's
markup parser would eat. We escape() every model-sourced fragment we
splice into our own markup, and the per-task body Static renders with
markup=False so even pathological inputs can't crash the screen.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from rich.text import Text
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Collapsible, Static


@dataclass(frozen=True)
class PlanTask:
    """One task parsed out of TASKS.md.

    Each field defaults to empty/empty-list so a partially-formed task
    (model omitted Files or Test command) still renders without raising.
    """

    task_id: str
    title: str
    done: bool = False
    goal: str = ""
    files: str = ""
    acceptance: list[str] = field(default_factory=list)
    test_command: str = ""


# Matches both pending and done task headers:
#   ## T001: Add feature
#   ## [✓] T001: Add feature   (marked done by run_plan)
# Group 1: optional mark inside [...], group 2: numeric id, group 3: title.
_TASK_HEADER_RE = re.compile(
    r"^##\s+(?:\[(?P<mark>[^\]]*)\]\s+)?(?P<id>T\d{3,}):\s*(?P<title>.*)$",
    re.MULTILINE,
)


def parse_tasks_md(text: str) -> list[PlanTask]:
    """Split TASKS.md content into a list of PlanTask records.

    Tolerant of missing fields: any of Goal/Files/Acceptance/Test command
    can be absent. Anything before the first `## T###:` heading is
    discarded as conversational lead-in (mirrors `_maybe_save_plan`).
    """
    if not text:
        return []
    headers = list(_TASK_HEADER_RE.finditer(text))
    if not headers:
        return []
    tasks: list[PlanTask] = []
    for i, m in enumerate(headers):
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        body = text[m.end() : end]
        mark = (m.group("mark") or "").strip()
        done = mark in ("✓", "x", "X")
        tasks.append(
            _build_task(
                task_id=m.group("id"),
                title=m.group("title").strip(),
                body=body,
                done=done,
            )
        )
    return tasks


def _build_task(*, task_id: str, title: str, body: str, done: bool = False) -> PlanTask:
    """Extract the five conventional fields out of one task's body slab.

    We walk lines top-down: a "Goal:" / "Files:" / "Test command:" line
    sets the corresponding scalar; an "Acceptance:" line opens a bullet
    list that absorbs subsequent "- ..." lines until the next labelled
    field or a blank-separated paragraph break. The format is loose
    enough that real planner output (which sometimes inlines whitespace
    or skips fields) survives.
    """
    goal = ""
    files = ""
    test_command = ""
    acceptance: list[str] = []
    in_acceptance = False
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            in_acceptance = False
            continue
        lower = line.lower()
        if lower.startswith("goal:"):
            goal = line[len("goal:") :].strip()
            in_acceptance = False
        elif lower.startswith("files:"):
            files = line[len("files:") :].strip()
            in_acceptance = False
        elif lower.startswith("test command:"):
            test_command = line[len("test command:") :].strip()
            in_acceptance = False
        elif lower.startswith("acceptance:"):
            in_acceptance = True
            # In case the model put a bullet on the same line as "Acceptance:".
            rest = line[len("acceptance:") :].strip()
            if rest:
                acceptance.append(rest.lstrip("- ").strip())
        elif in_acceptance and line.startswith("-"):
            acceptance.append(line.lstrip("- ").strip())
        else:
            # Stray prose between fields — ignore. Keeps us robust against
            # the model adding a sentence of context that isn't a field.
            in_acceptance = False
    return PlanTask(
        task_id=task_id,
        title=title,
        done=done,
        goal=goal,
        files=files,
        acceptance=acceptance,
        test_command=test_command,
    )


def _render_task_body(task: PlanTask) -> Text:
    """Build a Rich Text for one task's body.

    Text built additively from append() calls is immune to markup
    injection: each `append(s, style=...)` treats `s` as a literal string
    regardless of any `[`, `]`, `=` it contains. That's why the per-task
    Static below uses markup=False but still gets coloured spans.
    """
    out = Text()
    if task.done:
        out.append(f"✓ {task.task_id}: {task.title}\n", style="bold #7fc090 strike")
    else:
        out.append(f"◻ {task.task_id}: {task.title}\n", style="bold")
    if task.done:
        return out  # collapsed view for completed tasks — no need for details
    if task.goal:
        out.append("Goal: ", style="dim bold")
        out.append(f"{task.goal}\n")
    if task.files:
        out.append("Files: ", style="dim bold")
        out.append(f"{task.files}\n", style="dim")
    if task.acceptance:
        out.append("Acceptance:\n", style="dim bold")
        for item in task.acceptance:
            out.append("  • ", style="dim")
            out.append(f"{item}\n")
    if task.test_command:
        out.append("Test: ", style="dim bold")
        out.append(f"{task.test_command}\n", style="dim italic")
    return out


class PlanCard(Widget):
    """Inline expanded-by-default card showing parsed TASKS.md."""

    DEFAULT_CSS = """
    PlanCard {
        height: auto;
        background: #0f0f0f;
        margin: 1 0 0 0;
        padding: 0;
    }
    PlanCard Collapsible {
        background: #0f0f0f;
        border: none;
        padding: 0;
        margin: 0;
    }
    PlanCard Collapsible > Contents {
        background: #161616;
        padding: 0 1;
        color: #c0c0c0;
    }
    PlanCard CollapsibleTitle {
        background: #0f0f0f;
        padding: 0;
        color: #c0c0c0;
    }
    PlanCard Static.plan-task {
        height: auto;
        background: #161616;
        color: #c0c0c0;
        padding: 0 0 1 0;
    }
    PlanCard Static.plan-empty {
        height: auto;
        background: #161616;
        color: #707070;
        padding: 0;
    }
    """

    def __init__(self, tasks: list[PlanTask], *, collapsed: bool = False) -> None:
        super().__init__()
        self._tasks = list(tasks)
        self._collapsed = collapsed

    @classmethod
    def from_tasks_md(cls, text: str, *, collapsed: bool = False) -> PlanCard:
        """Parse TASKS.md text and return a ready-to-mount card."""
        return cls(parse_tasks_md(text), collapsed=collapsed)

    @property
    def tasks(self) -> list[PlanTask]:
        return list(self._tasks)

    def _title(self) -> str:
        n = len(self._tasks)
        done = sum(1 for t in self._tasks if t.done)
        noun = "task" if n == 1 else "tasks"
        # All literals here — no model-sourced text in the title, so
        # markup=True is safe and gets us the bold/dim styling.
        if done:
            return f"[bold]📋 Plan[/bold] [dim]({done}/{n} {noun})[/dim]"
        return f"[bold]📋 Plan[/bold] [dim]({n} {noun})[/dim]"

    def compose(self) -> ComposeResult:
        # collapsed=False: plan is the headline artefact of a plan-mode
        # turn, not background noise. User can fold it manually via the
        # Collapsible chevron if they want.
        with Collapsible(title=self._title(), collapsed=self._collapsed):
            if not self._tasks:
                yield Static("(empty plan)", classes="plan-empty", markup=False)
                return
            for task in self._tasks:
                # markup=False because the Text already carries its own
                # styled spans — letting Rich also markup-parse it would
                # both double-parse and re-introduce the injection risk
                # we just avoided by going through Text.append().
                yield Static(_render_task_body(task), classes="plan-task", markup=False)


__all__ = ["PlanCard", "PlanTask", "parse_tasks_md"]
