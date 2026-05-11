"""Unit tests for PlanCard — the inline expanded card that surfaces the
planner's TASKS.md artefact in the chat log."""

from __future__ import annotations

import pytest
from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import Collapsible, Static

from code_scalpel.tui.widgets.plan_card import (
    PlanCard,
    PlanTask,
    _render_task_body,
    parse_tasks_md,
)

_SAMPLE_TASKS_MD = """\
## T001: Add config loader

Goal: Load YAML config into a pydantic model.
Files: code_scalpel/config.py, tests/test_config.py
Acceptance:
- AppConfig.from_path raises on missing file
- Default profile is `coder-14b`
Test command: pytest tests/test_config.py -q

## T002: Add LLM adapter

Goal: Wrap OpenAI client for LM Studio.
Files: code_scalpel/llm_adapter.py
Acceptance:
- chat() returns ChatResponse
- stream() yields tokens
Test command: pytest tests/test_llm_adapter.py -q

## T003: Wire CLI entry point

Goal: typer-based `code-scalpel` command.
Files: code_scalpel/cli.py
Acceptance:
- `code-scalpel --help` exits 0
Test command: manual
"""


# ── parsing ──────────────────────────────────────────────────────────────────


def test_parse_three_tasks_round_trips_titles_and_ids() -> None:
    tasks = parse_tasks_md(_SAMPLE_TASKS_MD)
    assert [t.task_id for t in tasks] == ["T001", "T002", "T003"]
    assert [t.title for t in tasks] == [
        "Add config loader",
        "Add LLM adapter",
        "Wire CLI entry point",
    ]


def test_parse_extracts_all_fields() -> None:
    tasks = parse_tasks_md(_SAMPLE_TASKS_MD)
    t1 = tasks[0]
    assert t1.goal == "Load YAML config into a pydantic model."
    assert t1.files == "code_scalpel/config.py, tests/test_config.py"
    assert t1.acceptance == [
        "AppConfig.from_path raises on missing file",
        "Default profile is `coder-14b`",
    ]
    assert t1.test_command == "pytest tests/test_config.py -q"


def test_parse_skips_conversational_lead_in() -> None:
    """Anything before the first `## T###:` heading is dropped — mirrors
    `_maybe_save_plan` behaviour, so the card and the persisted file
    stay aligned."""
    src = "Sure, here's the plan!\n\n" + _SAMPLE_TASKS_MD
    tasks = parse_tasks_md(src)
    assert len(tasks) == 3
    assert tasks[0].task_id == "T001"


def test_parse_handles_missing_optional_fields() -> None:
    src = "## T042: Minimal task\n\nGoal: something\n"
    tasks = parse_tasks_md(src)
    assert len(tasks) == 1
    assert tasks[0].goal == "something"
    assert tasks[0].files == ""
    assert tasks[0].acceptance == []
    assert tasks[0].test_command == ""


def test_parse_empty_string_yields_no_tasks() -> None:
    assert parse_tasks_md("") == []


def test_parse_text_without_headers_yields_no_tasks() -> None:
    assert parse_tasks_md("just some prose\nno headings at all") == []


# ── widget ───────────────────────────────────────────────────────────────────


def test_from_tasks_md_builds_card_with_correct_task_count() -> None:
    card = PlanCard.from_tasks_md(_SAMPLE_TASKS_MD)
    assert len(card.tasks) == 3


def test_header_reports_task_count_for_plural() -> None:
    card = PlanCard.from_tasks_md(_SAMPLE_TASKS_MD)
    title = card._title()
    assert "3 tasks" in title
    assert "📋" in title


def test_header_reports_task_count_for_singular() -> None:
    card = PlanCard.from_tasks_md("## T001: Only one\n\nGoal: foo\n")
    title = card._title()
    assert "1 task" in title
    # Make sure we didn't double-pluralise into "1 tasks".
    assert "1 tasks" not in title


def test_header_zero_tasks_for_empty_plan() -> None:
    card = PlanCard.from_tasks_md("")
    title = card._title()
    assert "0 tasks" in title


# ── markup safety ────────────────────────────────────────────────────────────


def test_task_with_bracketed_title_does_not_crash() -> None:
    """Rich's markup parser explodes on stray brackets — make sure the
    body renderer survives a title like `[Brackets] and [foo=bar]`."""
    src = (
        "## T001: Refactor [Brackets] and [foo=bar]\n\n"
        "Goal: weird title shouldn't break rendering\n"
        "Files: a.py, [weird].py\n"
        "Acceptance:\n"
        "- handles [brackets] in items\n"
        "Test command: pytest -k '[edge]'\n"
    )
    card = PlanCard.from_tasks_md(src)
    assert len(card.tasks) == 1
    # The body is a rich.Text built additively — markup parsing is
    # bypassed entirely. Render to plain string to prove it.
    body = _render_task_body(card.tasks[0])
    assert isinstance(body, Text)
    plain = body.plain
    assert "[Brackets]" in plain
    assert "[foo=bar]" in plain
    assert "[weird].py" in plain
    assert "[brackets]" in plain


class _Harness(App[None]):
    """Minimal Textual App that hosts a single PlanCard so compose() can
    run in a real DOM context. Used by the few tests that need to verify
    end-to-end widget mounting; the parser tests don't need this."""

    def __init__(self, card: PlanCard) -> None:
        super().__init__()
        self._card = card

    def compose(self) -> ComposeResult:
        yield self._card


@pytest.mark.asyncio
async def test_task_with_brackets_compose_mounts_cleanly() -> None:
    """End-to-end: a bracket-laden task title must not blow up the live
    compose path — Rich markup parser is the usual culprit."""
    src = "## T001: Title [x=1]\n\nGoal: g\nFiles: [a].py\nAcceptance:\n- [item]\n"
    card = PlanCard.from_tasks_md(src)
    app = _Harness(card)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.05)
        # Card hosts exactly one Collapsible holding the per-task Statics.
        collapsibles = list(app.query(Collapsible))
        assert len(collapsibles) == 1
        statics = list(app.query("PlanCard Static.plan-task"))
        assert len(statics) == 1
        plain = _static_plain(statics[0])
        assert "Title [x=1]" in plain
        assert "[a].py" in plain
        assert "[item]" in plain


@pytest.mark.asyncio
async def test_empty_plan_mounts_empty_marker() -> None:
    """Empty TASKS.md → card still mounts and shows the "(empty plan)"
    placeholder rather than crashing."""
    card = PlanCard.from_tasks_md("")
    assert card.tasks == []
    app = _Harness(card)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.05)
        empties = list(app.query("PlanCard Static.plan-empty"))
        assert len(empties) == 1
        assert "(empty plan)" in _static_plain(empties[0])


# ── helpers ──────────────────────────────────────────────────────────────────


def _static_plain(s: Static) -> str:
    """Best-effort plain-text view of whatever a Static is rendering.

    Textual ≥0.80 stores the Static body on a name-mangled `__content`
    attribute (no public renderable accessor). We pull from there so
    tests don't depend on internal `render()`, which would need a live
    visual pipeline."""
    raw = getattr(s, "_Static__content", "")
    if isinstance(raw, Text):
        return raw.plain
    return str(raw)


def test_plan_task_dataclass_defaults() -> None:
    """Defensive: PlanTask must default optional fields, so a partial
    parse never raises on field access."""
    t = PlanTask(task_id="T001", title="x")
    assert t.goal == ""
    assert t.files == ""
    assert t.acceptance == []
    assert t.test_command == ""
