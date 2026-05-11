"""Local heuristic that maps a free-text task to a TaskType.

Pure function, no LLM, no I/O. Used by the planner/autonomous loop to
decide which mode (ask / plan / step / debug) the agent should default
to for a given user request. Plan §10 + §21.
"""

from __future__ import annotations

import re
from enum import StrEnum

__all__ = ["TaskType", "classify"]


class TaskType(StrEnum):
    QUESTION = "question"
    DESIGN = "design"
    IMPLEMENT = "implement"
    DEBUG = "debug"
    REFACTOR = "refactor"
    NEW_PROJECT = "new_project"


# Order matters: earlier categories win on overlap (e.g. "fix and add" → DEBUG).
_RULES: tuple[tuple[TaskType, tuple[str, ...]], ...] = (
    (
        TaskType.DEBUG,
        ("fix", "bug", "error", "errors", "traceback", "fails", "failing", "broken", "crash"),
    ),
    (TaskType.QUESTION, ("explain", "what", "what's", "how", "why", "describe", "where")),
    (TaskType.REFACTOR, ("refactor", "rename", "move", "restructure", "extract", "inline")),
    (TaskType.IMPLEMENT, ("add", "implement", "create", "write", "build", "make")),
)

# IMPLEMENT triggers fall back to DESIGN when the task is long enough to imply
# scope that needs planning. 60 chars matches plan §21.
_IMPLEMENT_TO_DESIGN_LEN = 60


def classify(task: str) -> TaskType:
    """Classify a task by keywords. Falls back to DESIGN."""
    text = task.lower()
    for task_type, keywords in _RULES:
        if _contains_any_word(text, keywords):
            if task_type is TaskType.IMPLEMENT and len(task) >= _IMPLEMENT_TO_DESIGN_LEN:
                return TaskType.DESIGN
            return task_type
    return TaskType.DESIGN


def _contains_any_word(text: str, words: tuple[str, ...]) -> bool:
    # Word-boundary match so "prefix" doesn't trigger "fix" and "explainer"
    # doesn't trigger "explain". Allows punctuation/contractions naturally
    # because \b sits between alphanumeric and non-alphanumeric.
    pattern = r"\b(?:" + "|".join(re.escape(w) for w in words) + r")\b"
    return re.search(pattern, text) is not None
