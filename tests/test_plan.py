from __future__ import annotations

from code_scalpel.plan import Task, parse_tasks_md, serialize_tasks


def test_parse_empty_file_returns_empty_tuple() -> None:
    assert parse_tasks_md("") == ()
    assert parse_tasks_md("   \n\n") == ()


def test_parse_single_task() -> None:
    text = (
        "## T001: Add note search\n"
        "\n"
        "Goal: search by title\n"
        "Files: notes.py\n"
        "Acceptance:\n"
        "- works\n"
        "Test command: pytest\n"
    )
    tasks = parse_tasks_md(text)
    assert len(tasks) == 1
    t = tasks[0]
    assert t.id == "T001"
    assert t.title == "Add note search"
    assert t.done is False
    assert "Goal: search by title" in t.body
    assert "Test command: pytest" in t.body


def test_parse_multiple_tasks_keeps_order() -> None:
    text = "## T001: First\n\nGoal: a\n\n## T002: Second\n\nGoal: b\n\n## T003: Third\n\nGoal: c\n"
    tasks = parse_tasks_md(text)
    assert [t.id for t in tasks] == ["T001", "T002", "T003"]
    assert [t.title for t in tasks] == ["First", "Second", "Third"]


def test_parse_mixed_done_and_pending() -> None:
    text = (
        "## [✓] T001: Done already\n\nGoal: x\n\n"
        "## T002: Not yet\n\nGoal: y\n\n"
        "## [x] T003: Also done\n\nGoal: z\n"
    )
    tasks = parse_tasks_md(text)
    assert tasks[0].done is True
    assert tasks[1].done is False
    assert tasks[2].done is True


def test_parse_preserves_preamble() -> None:
    """Free text before the first ## heading is not a task — it must be
    ignored by parse but survive serialise round-trip."""
    text = (
        "# Plan for v0.3\n\n"
        "Some intro paragraph the planner emitted.\n\n"
        "## T001: First\n\nGoal: do it\n"
    )
    tasks = parse_tasks_md(text)
    assert len(tasks) == 1
    out = serialize_tasks(tasks, text)
    assert out.startswith("# Plan for v0.3")
    assert "Some intro paragraph" in out


def test_serialize_round_trip_is_idempotent() -> None:
    text = (
        "## T001: A task\n\n"
        "Goal: x\n"
        "Files: a.py\n"
        "Acceptance:\n"
        "- ok\n"
        "Test command: pytest\n\n"
        "## [✓] T002: Done one\n\n"
        "Goal: y\n"
    )
    tasks = parse_tasks_md(text)
    out = serialize_tasks(tasks, text)
    # parse(serialize(x)) == parse(x) — and serialize is a no-op when
    # statuses match the on-disk state.
    assert out == text
    assert parse_tasks_md(out) == tasks


def test_serialize_flips_status_only_on_changed_task() -> None:
    text = "## T001: A task\n\nGoal: x\n\n## T002: Another\n\nGoal: y\n"
    tasks = parse_tasks_md(text)
    # Mark T001 done, leave T002.
    flipped = (
        Task(id=tasks[0].id, title=tasks[0].title, body=tasks[0].body, done=True),
        tasks[1],
    )
    out = serialize_tasks(flipped, text)
    assert "## [✓] T001: A task" in out
    assert "## T002: Another" in out
    # Body content untouched.
    assert "Goal: x" in out
    assert "Goal: y" in out


def test_parse_tolerates_malformed_heading_without_colon() -> None:
    """Planner sometimes drops the colon — '## T001 Title' instead of
    '## T001: Title'. We still extract it; better than crashing the run."""
    text = "## T001 No colon here\n\nGoal: z\n"
    tasks = parse_tasks_md(text)
    assert len(tasks) == 1
    assert tasks[0].id == "T001"
    assert tasks[0].title == "No colon here"


def test_serialize_preserves_trailing_text() -> None:
    """Text after the last task body (notes, references) survives the
    round-trip — the file may carry hand-written context the agent
    should never destroy."""
    text = (
        "## T001: Single task\n\nGoal: x\n"
        "\n"
        "---\n"
        "Notes: hand-written addendum the user added by hand.\n"
    )
    tasks = parse_tasks_md(text)
    out = serialize_tasks(tasks, text)
    assert "hand-written addendum" in out
