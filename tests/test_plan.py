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


# ─── v0.14 step 1: JSON schema path ─────────────────────────────


def test_parse_tasks_json_minimal() -> None:
    """Schema-validated JSON path: one task with all required fields,
    no completed list."""
    from code_scalpel.plan import parse_tasks_json

    text = (
        '{"tasks": [{"id": "T001", "title": "make a", '
        '"goal": "create a.py", "files": ["a.py"], '
        '"acceptance": ["a exists"], "test_command": null}]}'
    )
    tasks = parse_tasks_json(text)
    assert len(tasks) == 1
    t = tasks[0]
    assert t.id == "T001"
    assert t.title == "make a"
    assert t.goal == "create a.py"
    assert t.files == ("a.py",)
    assert t.acceptance == ("a exists",)
    assert t.skills == ()  # absent in JSON → empty tuple
    assert t.test_command is None
    assert t.done is False


def test_parse_tasks_json_completed_marks_done() -> None:
    """Sibling `completed` list (runtime-state, not in model output)
    flips matching task IDs to done. Lets us reuse the same schema
    for the model emit AND for persistent state."""
    from code_scalpel.plan import parse_tasks_json

    text = (
        '{"tasks": ['
        '{"id": "T001", "title": "a", "goal": "x", "files": [], '
        '"acceptance": [], "test_command": null},'
        '{"id": "T002", "title": "b", "goal": "y", "files": [], '
        '"acceptance": [], "test_command": "pytest"}'
        '], "completed": ["T001"]}'
    )
    tasks = parse_tasks_json(text)
    assert tasks[0].done is True
    assert tasks[1].done is False
    assert tasks[1].test_command == "pytest"


def test_parse_tasks_json_invalid_returns_empty() -> None:
    """Malformed JSON → empty tuple, not crash. Caller decides what to
    do (fall back to markdown, prompt the model to retry, etc)."""
    from code_scalpel.plan import parse_tasks_json

    assert parse_tasks_json("") == ()
    assert parse_tasks_json("not a json {") == ()
    assert parse_tasks_json("[]") == ()  # not a dict at the top
    assert parse_tasks_json('{"foo": 1}') == ()  # no tasks


def test_serialize_tasks_json_roundtrip() -> None:
    """Render → re-parse → fields match. Done-status round-trips
    through the sibling `completed` list."""
    from code_scalpel.plan import Task, parse_tasks_json, serialize_tasks_json

    tasks = (
        Task(
            id="T001",
            title="a",
            body="",
            done=True,
            goal="create",
            files=("a.py",),
            acceptance=("exists",),
            skills=("python",),
            test_command="pytest",
        ),
        Task(id="T002", title="b", body="", done=False, goal="g", test_command=None),
    )
    text = serialize_tasks_json(tasks)
    reparsed = parse_tasks_json(text)
    assert reparsed[0].id == "T001"
    assert reparsed[0].done is True
    assert reparsed[0].skills == ("python",)
    assert reparsed[1].test_command is None


def test_render_tasks_markdown_skips_empty_fields() -> None:
    """Markdown render is a derived view — empty typed fields don't
    print empty lines, kept compact."""
    from code_scalpel.plan import Task, render_tasks_markdown

    tasks = (
        Task(
            id="T001",
            title="bare",
            body="",
            done=False,
            goal="g",
            files=("a.py",),
            test_command=None,
        ),
    )
    md = render_tasks_markdown(tasks)
    assert "## T001: bare" in md
    assert "Goal: g" in md
    assert "Files: a.py" in md
    assert "Test command: manual" in md
    # No Acceptance / Skills lines since the fields are empty.
    assert "Acceptance:" not in md
    assert "Skills:" not in md


def test_render_tasks_markdown_done_marker() -> None:
    """Done tasks get the [✓] marker — matches legacy markdown."""
    from code_scalpel.plan import Task, render_tasks_markdown

    md = render_tasks_markdown((Task(id="T001", title="x", body="", done=True, goal="g"),))
    assert "## [✓] T001: x" in md
