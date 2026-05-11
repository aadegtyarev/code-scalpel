"""Tests for the local task classifier (plan §21).

Pure function, no fixtures needed — just exercise the keyword rules.
"""

from __future__ import annotations

import pytest

from code_scalpel.classifier import TaskType, classify


@pytest.mark.parametrize(
    "task",
    [
        "fix crash when query is empty",
        "bug: parser returns None",
        "Tests are failing on CI",
        "TypeError traceback in step.py",
        "the export pipeline is broken",
    ],
)
def test_debug_keywords(task: str) -> None:
    assert classify(task) is TaskType.DEBUG


@pytest.mark.parametrize(
    "task",
    [
        "explain how the agent loop works",
        "what is the role of project_map?",
        "How does compact work?",
        "Why do we strip user_msg before history?",
        "describe the streaming protocol",
    ],
)
def test_question_keywords(task: str) -> None:
    assert classify(task) is TaskType.QUESTION


@pytest.mark.parametrize(
    "task",
    [
        "refactor the parser",
        "rename _MAX_TOOL_ROUNDS to MAX_ROUNDS",
        "move classifier into core/",
        "restructure tests directory",
        "extract _is_loop into a helper module",
    ],
)
def test_refactor_keywords(task: str) -> None:
    assert classify(task) is TaskType.REFACTOR


@pytest.mark.parametrize(
    "task",
    [
        "add /reset command",
        "implement timeout",
        "create config dataclass",
        "write a test for compact",
        "build the docker image",
    ],
)
def test_implement_short(task: str) -> None:
    assert classify(task) is TaskType.IMPLEMENT


def test_implement_long_falls_back_to_design() -> None:
    long_task = (
        "add a planner mode that produces TASKS.md and lets the user "
        "step through items one by one with confirmation"
    )
    assert len(long_task) >= 60
    assert classify(long_task) is TaskType.DESIGN


@pytest.mark.parametrize(
    "task",
    [
        "",
        "   ",
        "we should think about caching strategies",
        "audit the security model",
    ],
)
def test_default_is_design(task: str) -> None:
    assert classify(task) is TaskType.DESIGN


def test_debug_wins_over_implement_on_overlap() -> None:
    # Both "fix" (DEBUG) and "add" (IMPLEMENT) match — DEBUG comes first.
    assert classify("fix the bug and add a test") is TaskType.DEBUG


def test_word_boundary_avoids_substring_false_positive() -> None:
    # "prefix" must NOT trigger "fix" → DEBUG; the task is really a question.
    assert classify("explain how the prefix module works") is TaskType.QUESTION
    # "addendum" must NOT trigger "add" → IMPLEMENT either.
    assert classify("the addendum file is unclear") is TaskType.DESIGN


def test_case_insensitive() -> None:
    assert classify("FIX THE CRASH") is TaskType.DEBUG
    assert classify("Refactor Parser") is TaskType.REFACTOR


def test_new_project_value_exists_even_if_unreachable_from_classify() -> None:
    # NEW_PROJECT is triggered elsewhere (e.g. `code-scalpel init`), not by
    # the heuristic — but the enum must expose the value so callers can match.
    assert TaskType.NEW_PROJECT.value == "new_project"
