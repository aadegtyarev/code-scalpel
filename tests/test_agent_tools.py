"""Tests for tool-call parsing and execution."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from code_scalpel.tools.agent_tools import (
    ToolCall,
    execute,
    format_result,
    parse_tool_calls,
)

# ── parsing ──────────────────────────────────────────────────────────────────


def test_parse_single_tool_call() -> None:
    text = textwrap.dedent("""\
        I need to look at the file first.

        <TOOL: read_file>
        code_scalpel/agent.py
        </TOOL>
        """)
    calls = parse_tool_calls(text)
    assert len(calls) == 1
    assert calls[0].name == "read_file"
    assert calls[0].body == "code_scalpel/agent.py"


def test_parse_multiple_tool_calls() -> None:
    text = textwrap.dedent("""\
        <TOOL: read_file>
        a.py
        </TOOL>

        and another:

        <TOOL: read_file>
        b.py
        </TOOL>
        """)
    calls = parse_tool_calls(text)
    assert len(calls) == 2
    assert [c.body for c in calls] == ["a.py", "b.py"]


def test_parse_returns_empty_when_no_calls() -> None:
    assert parse_tool_calls("just text, no tools") == []


def test_parse_strips_body_whitespace() -> None:
    text = "<TOOL: read_file>\n   foo.py   \n</TOOL>"
    calls = parse_tool_calls(text)
    assert calls[0].body == "foo.py"


# ── execution: read_file ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_read_file_returns_content(tmp_path: Path) -> None:
    (tmp_path / "hi.py").write_text("def hi():\n    pass\n")
    call = ToolCall(name="read_file", body="hi.py")
    result = await execute(call, tmp_path)
    assert result.ok
    assert "def hi" in result.output
    assert "path: hi.py" in result.output


@pytest.mark.asyncio
async def test_read_file_rejects_missing(tmp_path: Path) -> None:
    call = ToolCall(name="read_file", body="does_not_exist.py")
    result = await execute(call, tmp_path)
    assert not result.ok
    assert "not found" in result.output


@pytest.mark.asyncio
async def test_read_file_rejects_absolute_path(tmp_path: Path) -> None:
    call = ToolCall(name="read_file", body="/etc/passwd")
    result = await execute(call, tmp_path)
    assert not result.ok
    assert "inside the project" in result.output


@pytest.mark.asyncio
async def test_read_file_rejects_parent_escape(tmp_path: Path) -> None:
    call = ToolCall(name="read_file", body="../etc/passwd")
    result = await execute(call, tmp_path)
    assert not result.ok
    assert "inside the project" in result.output


@pytest.mark.asyncio
async def test_read_file_missing_path_arg(tmp_path: Path) -> None:
    call = ToolCall(name="read_file", body="")
    result = await execute(call, tmp_path)
    assert not result.ok
    assert "missing" in result.output


@pytest.mark.asyncio
async def test_read_file_window_args_forwarded(tmp_path: Path) -> None:
    """The dispatch wrapper threads start_line/end_line down to read_file."""
    (tmp_path / "big.py").write_text("\n".join(f"row {i}" for i in range(50)))
    call = ToolCall(
        name="read_file",
        body='{"path": "big.py", "start_line": 10, "end_line": 12}',
    )
    result = await execute(call, tmp_path)
    assert result.ok
    assert "row 9" in result.output  # 1-based line 10
    assert "row 11" in result.output
    assert "row 0" not in result.output
    assert "row 20" not in result.output


@pytest.mark.asyncio
async def test_read_file_find_arg_forwarded(tmp_path: Path) -> None:
    """find=<substr> + context lands the model on each hit."""
    lines = [f"row {i}" for i in range(50)]
    lines[20] = "def target():"
    (tmp_path / "src.py").write_text("\n".join(lines))
    call = ToolCall(
        name="read_file",
        body='{"path": "src.py", "find": "target", "context": 1}',
    )
    result = await execute(call, tmp_path)
    assert result.ok
    assert "def target()" in result.output
    assert "1 occurrence(s)" in result.output


@pytest.mark.asyncio
async def test_read_file_accepts_string_ints(tmp_path: Path) -> None:
    """Some clients stringify numeric args — must still work."""
    (tmp_path / "f.py").write_text("\n".join(f"L{i}" for i in range(30)))
    call = ToolCall(
        name="read_file",
        body='{"path": "f.py", "start_line": "5", "end_line": "7"}',
    )
    result = await execute(call, tmp_path)
    assert result.ok
    assert "L4" in result.output
    assert "L6" in result.output


# ── execution: map_file ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_map_file_returns_drilldown_block(tmp_path: Path) -> None:
    """`map_file` is the drilldown tool — give the model one file's
    signatures + docstrings + intra-project imports, not the bodies."""
    (tmp_path / "thing.py").write_text(
        'class Thing:\n    """Does a thing."""\n    def do(self) -> int:\n        return 42\n'
    )
    call = ToolCall(name="map_file", body='{"path": "thing.py"}')
    result = await execute(call, tmp_path)
    assert result.ok
    assert "thing.py" in result.output
    assert "class Thing" in result.output
    assert "def do(self) -> int" in result.output
    # The body should NOT leak through — drilldown is signatures only
    assert "return 42" not in result.output


@pytest.mark.asyncio
async def test_map_file_handles_legacy_text_body(tmp_path: Path) -> None:
    """Legacy `<TOOL: map_file>` text form — bare path as the body."""
    (tmp_path / "x.py").write_text("def f(): pass\n")
    call = ToolCall(name="map_file", body="x.py")
    result = await execute(call, tmp_path)
    assert result.ok
    assert "x.py" in result.output
    assert "def f()" in result.output


@pytest.mark.asyncio
async def test_map_file_empty_arg_returns_project_tree(tmp_path: Path) -> None:
    """`map_file` is a legacy alias for `project_map`; with no path
    argument it falls into tree-mode (was an error in the old
    standalone map_file)."""
    (tmp_path / "x.py").write_text("x = 1\n")
    call = ToolCall(name="map_file", body="")
    result = await execute(call, tmp_path)
    assert result.ok
    assert "x.py" in result.output


@pytest.mark.asyncio
async def test_map_file_rejects_absolute_path(tmp_path: Path) -> None:
    call = ToolCall(name="map_file", body='{"path": "/etc/passwd"}')
    result = await execute(call, tmp_path)
    assert not result.ok
    assert "inside the project" in result.output


@pytest.mark.asyncio
async def test_map_file_rejects_parent_escape(tmp_path: Path) -> None:
    call = ToolCall(name="map_file", body='{"path": "../sneaky.py"}')
    result = await execute(call, tmp_path)
    assert not result.ok
    assert "inside the project" in result.output


@pytest.mark.asyncio
async def test_map_file_reports_missing_file(tmp_path: Path) -> None:
    call = ToolCall(name="map_file", body='{"path": "nope.py"}')
    result = await execute(call, tmp_path)
    assert not result.ok
    assert "not found" in result.output


# ── execution: grep ──────────────────────────────────────────────────────────


_HAS_RG = pytest.mark.skipif(
    __import__("shutil").which("rg") is None,
    reason="ripgrep (rg) not installed",
)


@_HAS_RG
@pytest.mark.asyncio
async def test_grep_finds_pattern(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def needle(): pass\n")
    (tmp_path / "b.py").write_text("def haystack(): pass\n")
    call = ToolCall(name="grep", body="needle")
    result = await execute(call, tmp_path)
    assert result.ok
    assert "a.py" in result.output
    assert "needle" in result.output


@pytest.mark.asyncio
async def test_grep_missing_pattern(tmp_path: Path) -> None:
    call = ToolCall(name="grep", body="")
    result = await execute(call, tmp_path)
    assert not result.ok
    assert "missing pattern" in result.output


@_HAS_RG
@pytest.mark.asyncio
async def test_grep_rejects_parent_path(tmp_path: Path) -> None:
    call = ToolCall(name="grep", body="x\n../secrets")
    result = await execute(call, tmp_path)
    assert not result.ok
    assert "inside project" in result.output


# ── execution: run_tests ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_tests_passes_when_clean(tmp_path: Path) -> None:
    (tmp_path / "test_x.py").write_text("def test_a(): assert 1 == 1\n")
    call = ToolCall(name="run_tests", body="")
    result = await execute(call, tmp_path)
    assert result.ok
    assert "exit code: 0" in result.output
    # tmp_path has no skill marker → fallback path is announced
    assert "using skill: pytest (fallback)" in result.output


@pytest.mark.asyncio
async def test_run_tests_reports_failure(tmp_path: Path) -> None:
    (tmp_path / "test_x.py").write_text("def test_a(): assert 1 == 2\n")
    call = ToolCall(name="run_tests", body="")
    result = await execute(call, tmp_path)
    assert not result.ok
    assert "exit code:" in result.output
    assert "1" in result.output  # non-zero exit code
    assert "using skill: pytest (fallback)" in result.output


@pytest.mark.asyncio
async def test_run_tests_uses_python_skill_when_pyproject_present(tmp_path: Path) -> None:
    """A project with pyproject.toml routes through PythonSkill.test_cmd,
    so the recorded shell command must be exactly its pytest argv and
    the header must announce the active skill name."""
    from code_scalpel.tools.shell import ShellResult
    from tests.mocks import MockShellRunner

    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    runner = MockShellRunner([ShellResult("1 passed", 0)])
    call = ToolCall(name="run_tests", body="")
    result = await execute(call, tmp_path, runner=runner)
    assert result.ok
    assert result.output.startswith("using skill: python\n")
    assert runner.calls == [["pytest", "-x", "--tb=short", "--no-header", "-q"]]


@pytest.mark.asyncio
async def test_run_tests_uses_docker_skill_on_docker_only_project(tmp_path: Path) -> None:
    """A Dockerfile-only project (no pyproject.toml) routes through
    DockerSkill — `docker compose run --rm app pytest`. The header must
    say `using skill: docker`."""
    from code_scalpel.tools.shell import ShellResult
    from tests.mocks import MockShellRunner

    (tmp_path / "Dockerfile").write_text("FROM python:3.12\n")
    runner = MockShellRunner([ShellResult("1 passed", 0)])
    call = ToolCall(name="run_tests", body="")
    result = await execute(call, tmp_path, runner=runner)
    assert result.ok
    assert result.output.startswith("using skill: docker\n")
    assert runner.calls == [["docker", "compose", "run", "--rm", "app", "pytest"]]


@pytest.mark.asyncio
async def test_run_tests_falls_back_to_pytest_on_unrecognised_project(tmp_path: Path) -> None:
    """Empty tmp_path has no skill marker → fallback pytest argv,
    annotated with `(fallback)` so the user knows no skill detected."""
    from code_scalpel.tools.shell import ShellResult
    from tests.mocks import MockShellRunner

    runner = MockShellRunner([ShellResult("", 0)])
    call = ToolCall(name="run_tests", body="")
    result = await execute(call, tmp_path, runner=runner)
    assert result.ok
    assert result.output.startswith("using skill: pytest (fallback)\n")
    assert runner.calls == [["pytest", "-x", "--tb=short", "--no-header", "-q"]]


@pytest.mark.asyncio
async def test_unknown_tool_returns_error(tmp_path: Path) -> None:
    call = ToolCall(name="evaluate", body="any")
    result = await execute(call, tmp_path)
    assert not result.ok
    assert "unknown tool" in result.output
    assert "evaluate" in result.output


# ── formatting ───────────────────────────────────────────────────────────────


def test_format_result_round_trip() -> None:
    from code_scalpel.tools.agent_tools import ToolResult

    call = ToolCall(name="read_file", body="x.py")
    result = ToolResult(call=call, output="hello world", ok=True)
    rendered = format_result(result)
    assert rendered.startswith("<RESULT: read_file>")
    assert rendered.endswith("</RESULT>")
    assert "hello world" in rendered


# ── execution: goto_definition ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_goto_definition_finds_class(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("class Widget:\n    pass\n")
    call = ToolCall(name="goto_definition", body='{"name": "Widget"}')
    result = await execute(call, tmp_path)
    assert result.ok
    assert "a.py:1" in result.output
    assert "class" in result.output
    assert "Widget" in result.output


@pytest.mark.asyncio
async def test_goto_definition_disambiguates_method(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text(
        "class Foo:\n    def run(self):\n        pass\n\n"
        "class Bar:\n    def run(self):\n        pass\n"
    )
    call = ToolCall(name="goto_definition", body='{"name": "run"}')
    result = await execute(call, tmp_path)
    assert result.ok
    assert "Foo.run" in result.output
    assert "Bar.run" in result.output


@pytest.mark.asyncio
async def test_goto_definition_no_match_returns_helpful_message(tmp_path: Path) -> None:
    """Empty result is ok=True with a hint — the agent should fall back
    to grep, not error out."""
    (tmp_path / "a.py").write_text("def alpha(): pass\n")
    call = ToolCall(name="goto_definition", body='{"name": "beta"}')
    result = await execute(call, tmp_path)
    assert result.ok
    assert "no definition" in result.output.lower()
    assert "grep" in result.output  # hint to the agent


@pytest.mark.asyncio
async def test_goto_definition_missing_name_errors(tmp_path: Path) -> None:
    call = ToolCall(name="goto_definition", body="")
    result = await execute(call, tmp_path)
    assert not result.ok
    assert "missing" in result.output


# ── execution: find_references ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_find_references_returns_path_line_text(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def widget():\n    pass\n\nwidget()\n")
    call = ToolCall(name="find_references", body='{"name": "widget"}')
    result = await execute(call, tmp_path)
    assert result.ok
    # Two refs: definition + call site
    lines = result.output.splitlines()
    assert any("a.py:1:" in ln and "def widget" in ln for ln in lines)
    assert any("a.py:4:" in ln and "widget()" in ln for ln in lines)


@pytest.mark.asyncio
async def test_find_references_no_match(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def alpha(): pass\n")
    call = ToolCall(name="find_references", body='{"name": "beta"}')
    result = await execute(call, tmp_path)
    assert result.ok
    assert "no references" in result.output.lower()


@pytest.mark.asyncio
async def test_find_references_missing_name_errors(tmp_path: Path) -> None:
    call = ToolCall(name="find_references", body="")
    result = await execute(call, tmp_path)
    assert not result.ok
    assert "missing" in result.output


# ── execution: retrieve ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_retrieve_happy_path_returns_ranked_row(tmp_path: Path) -> None:
    """The output row must start with `path:line` — same shape as
    goto_definition — so the agent can fold retrieve hits into the same
    "click here" loop without a special parser."""
    (tmp_path / "a.py").write_text("def compact_context():\n    pass\n")
    call = ToolCall(name="retrieve", body='{"query": "compact"}')
    result = await execute(call, tmp_path)
    assert result.ok
    first = result.output.splitlines()[0]
    assert first.startswith("a.py:1")
    assert "compact_context" in first


@pytest.mark.asyncio
async def test_retrieve_with_path_scopes_search(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def needle(): pass\n")
    (tmp_path / "b.py").write_text("def needle(): pass\n")
    call = ToolCall(name="retrieve", body='{"query": "needle", "path": "a.py"}')
    result = await execute(call, tmp_path)
    assert result.ok
    assert "a.py" in result.output
    assert "b.py" not in result.output


@pytest.mark.asyncio
async def test_retrieve_no_match_returns_helpful_message(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def alpha(): pass\n")
    call = ToolCall(name="retrieve", body='{"query": "zzz_no_such_thing"}')
    result = await execute(call, tmp_path)
    assert result.ok
    assert "no symbol hits" in result.output
    assert "grep" in result.output


@pytest.mark.asyncio
async def test_retrieve_rejects_absolute_path(tmp_path: Path) -> None:
    call = ToolCall(
        name="retrieve",
        body='{"query": "foo", "path": "/etc/passwd"}',
    )
    result = await execute(call, tmp_path)
    assert not result.ok
    assert "inside the project" in result.output


# ── symlink escape guard (security fix from session review) ──────────────────


@pytest.mark.asyncio
async def test_read_file_rejects_symlink_pointing_outside_project(tmp_path: Path) -> None:
    """A symlink with a lexically clean name but a target outside the
    project must NOT be served. Lexical path validation (startswith /,
    ..) is the first gate; symlink resolution is the backstop. Without
    this, a tracked `secrets -> /etc/passwd` symlink would slip past
    read_file and leak host content into the model's context."""
    outside = tmp_path.parent / "secret_outside.txt"
    outside.write_text("HOST SECRET")
    project = tmp_path / "project"
    project.mkdir()
    (project / "ok.py").write_text("x = 1\n")
    (project / "leak").symlink_to(outside)

    call = ToolCall(name="read_file", body='{"path": "leak"}')
    result = await execute(call, project)
    assert not result.ok
    assert "inside the project" in result.output
    assert "HOST SECRET" not in result.output


@pytest.mark.asyncio
async def test_map_file_rejects_symlink_escape(tmp_path: Path) -> None:
    outside_dir = tmp_path.parent / "outside_pkg"
    outside_dir.mkdir(exist_ok=True)
    (outside_dir / "secret.py").write_text("def secret_fn(): pass\n")
    project = tmp_path / "project"
    project.mkdir()
    (project / "leak.py").symlink_to(outside_dir / "secret.py")

    call = ToolCall(name="map_file", body='{"path": "leak.py"}')
    result = await execute(call, project)
    assert not result.ok
    assert "inside the project" in result.output


# ── shell_exec dispatch ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_shell_exec_runs_command_in_yolo(tmp_path: Path) -> None:
    """yolo level passes every command straight to runner.run_shell."""
    from code_scalpel.tools.shell import ShellResult
    from tests.mocks import MockShellRunner

    runner = MockShellRunner([ShellResult("hello world\n", 0)])
    call = ToolCall(name="shell_exec", body='{"command": "echo hello world"}')

    result = await execute(call, tmp_path, runner=runner, trust="yolo")

    assert result.ok is True
    assert "exit code: 0" in result.output
    assert "hello world" in result.output
    assert runner.shell_calls == ["echo hello world"]


@pytest.mark.asyncio
async def test_shell_exec_refuses_in_skeptic_without_callback(tmp_path: Path) -> None:
    """skeptic + no confirm callback → refused. Probes / bench can't
    pop a UI; refusal points the user at how to wire one."""
    from tests.mocks import MockShellRunner

    runner = MockShellRunner()
    call = ToolCall(name="shell_exec", body='{"command": "ls -la"}')

    result = await execute(call, tmp_path, runner=runner, trust="skeptic")

    assert result.ok is False
    assert "refused" in result.output
    assert "confirm" in result.output.lower() or "skeptic" in result.output.lower()
    assert runner.shell_calls == []


@pytest.mark.asyncio
async def test_shell_exec_runs_in_skeptic_when_user_approves(tmp_path: Path) -> None:
    """skeptic + callback returning True → command runs after confirm."""
    from code_scalpel.tools.shell import ShellResult
    from tests.mocks import MockShellRunner

    runner = MockShellRunner([ShellResult("file1\nfile2\n", 0)])
    call = ToolCall(name="shell_exec", body='{"command": "ls"}')
    seen: list[str] = []

    async def approve(command: str) -> bool:
        seen.append(command)
        return True

    result = await execute(
        call, tmp_path, runner=runner, trust="skeptic", confirm_shell_exec=approve
    )

    assert result.ok is True
    assert seen == ["ls"]
    assert runner.shell_calls == ["ls"]


@pytest.mark.asyncio
async def test_shell_exec_refuses_in_skeptic_when_user_rejects(tmp_path: Path) -> None:
    """skeptic + callback returning False → refused with "user rejected"."""
    from tests.mocks import MockShellRunner

    runner = MockShellRunner()
    call = ToolCall(name="shell_exec", body='{"command": "ls"}')

    async def reject(command: str) -> bool:
        return False

    result = await execute(
        call, tmp_path, runner=runner, trust="skeptic", confirm_shell_exec=reject
    )

    assert result.ok is False
    assert "rejected" in result.output.lower()
    assert runner.shell_calls == []


@pytest.mark.asyncio
async def test_shell_exec_hard_block_short_circuits_confirm(tmp_path: Path) -> None:
    """`sudo` in skeptic mode is hard-blocked — the callback is NEVER
    asked because hard blocks fire before requires_confirm."""
    from tests.mocks import MockShellRunner

    runner = MockShellRunner()
    call = ToolCall(name="shell_exec", body='{"command": "sudo apt update"}')
    asked: list[str] = []

    async def track(command: str) -> bool:
        asked.append(command)
        return True

    result = await execute(call, tmp_path, runner=runner, trust="skeptic", confirm_shell_exec=track)

    assert result.ok is False
    assert "privilege" in result.output.lower() or "sudo" in result.output.lower()
    assert asked == []
    assert runner.shell_calls == []


@pytest.mark.asyncio
async def test_shell_exec_refuses_hard_block_in_optimist(tmp_path: Path) -> None:
    """optimist runs safe commands but hard-blocks rm -rf / etc."""
    from tests.mocks import MockShellRunner

    runner = MockShellRunner()
    call = ToolCall(name="shell_exec", body='{"command": "sudo apt update"}')

    result = await execute(call, tmp_path, runner=runner, trust="optimist")

    assert result.ok is False
    assert "refused" in result.output
    assert runner.shell_calls == []


@pytest.mark.asyncio
async def test_shell_exec_empty_command_errors(tmp_path: Path) -> None:
    from tests.mocks import MockShellRunner

    runner = MockShellRunner()
    call = ToolCall(name="shell_exec", body='{"command": "   "}')

    result = await execute(call, tmp_path, runner=runner, trust="yolo")

    assert result.ok is False
    assert "empty" in result.output.lower()


@pytest.mark.asyncio
async def test_shell_exec_truncates_huge_output(tmp_path: Path) -> None:
    from code_scalpel.tools.shell import ShellResult
    from tests.mocks import MockShellRunner

    huge = "x" * 10_000
    runner = MockShellRunner([ShellResult(huge, 0)])
    call = ToolCall(name="shell_exec", body='{"command": "cat huge.txt"}')

    result = await execute(call, tmp_path, runner=runner, trust="yolo")

    assert "truncated" in result.output
    # 4000-char cap + framing
    assert len(result.output) < 4500


# ── write_file: overwrite / replace lines / insert ───────────────────────────


@pytest.mark.asyncio
async def test_write_file_creates_new_file(tmp_path: Path) -> None:
    call = ToolCall(name="write_file", body='{"path": "new.py", "content": "x = 1\\n"}')
    result = await execute(call, tmp_path)
    assert result.ok is True
    assert (tmp_path / "new.py").read_text() == "x = 1\n"


@pytest.mark.asyncio
async def test_write_file_overwrites_existing(tmp_path: Path) -> None:
    (tmp_path / "f.py").write_text("old\n")
    call = ToolCall(name="write_file", body='{"path": "f.py", "content": "new\\n"}')
    result = await execute(call, tmp_path)
    assert result.ok is True
    assert (tmp_path / "f.py").read_text() == "new\n"


@pytest.mark.asyncio
async def test_write_file_creates_parent_dirs(tmp_path: Path) -> None:
    call = ToolCall(name="write_file", body='{"path": "a/b/c.py", "content": "x\\n"}')
    result = await execute(call, tmp_path)
    assert result.ok is True
    assert (tmp_path / "a/b/c.py").read_text() == "x\n"


@pytest.mark.asyncio
async def test_write_file_rejects_absolute_path(tmp_path: Path) -> None:
    call = ToolCall(name="write_file", body='{"path": "/etc/x", "content": "bad"}')
    result = await execute(call, tmp_path)
    assert result.ok is False
    assert "inside the project" in result.output


@pytest.mark.asyncio
async def test_write_file_rejects_parent_escape(tmp_path: Path) -> None:
    call = ToolCall(name="write_file", body='{"path": "../out", "content": "bad"}')
    result = await execute(call, tmp_path)
    assert result.ok is False


@pytest.mark.asyncio
async def test_write_file_replace_lines(tmp_path: Path) -> None:
    (tmp_path / "f.py").write_text("a\nb\nc\nd\ne\n")
    call = ToolCall(
        name="write_file",
        body='{"path": "f.py", "content": "B\\nC\\n", "start_line": 2, "end_line": 3}',
    )
    result = await execute(call, tmp_path)
    assert result.ok is True
    assert (tmp_path / "f.py").read_text() == "a\nB\nC\nd\ne\n"


@pytest.mark.asyncio
async def test_write_file_replace_lines_missing_end(tmp_path: Path) -> None:
    (tmp_path / "f.py").write_text("a\nb\n")
    call = ToolCall(
        name="write_file",
        body='{"path": "f.py", "content": "X\\n", "start_line": 1}',
    )
    result = await execute(call, tmp_path)
    assert result.ok is False


@pytest.mark.asyncio
async def test_write_file_replace_lines_on_missing_file(tmp_path: Path) -> None:
    call = ToolCall(
        name="write_file",
        body='{"path": "gone.py", "content": "X\\n", "start_line": 1, "end_line": 2}',
    )
    result = await execute(call, tmp_path)
    assert result.ok is False
    assert "not found" in result.output


@pytest.mark.asyncio
async def test_write_file_insert_after(tmp_path: Path) -> None:
    (tmp_path / "f.py").write_text("a\nc\n")
    call = ToolCall(
        name="write_file",
        body='{"path": "f.py", "content": "b\\n", "insert_after_line": 1}',
    )
    result = await execute(call, tmp_path)
    assert result.ok is True
    assert (tmp_path / "f.py").read_text() == "a\nb\nc\n"


@pytest.mark.asyncio
async def test_write_file_insert_at_top(tmp_path: Path) -> None:
    """`insert_after_line=0` means prepend."""
    (tmp_path / "f.py").write_text("a\nb\n")
    call = ToolCall(
        name="write_file",
        body='{"path": "f.py", "content": "z\\n", "insert_after_line": 0}',
    )
    result = await execute(call, tmp_path)
    assert result.ok is True
    assert (tmp_path / "f.py").read_text() == "z\na\nb\n"


@pytest.mark.asyncio
async def test_write_file_insert_and_replace_rejected_together(tmp_path: Path) -> None:
    (tmp_path / "f.py").write_text("a\nb\n")
    call = ToolCall(
        name="write_file",
        body=(
            '{"path": "f.py", "content": "X\\n", '
            '"start_line": 1, "end_line": 1, "insert_after_line": 1}'
        ),
    )
    result = await execute(call, tmp_path)
    assert result.ok is False


@pytest.mark.asyncio
async def test_write_file_replace_clamps_end_to_eof(tmp_path: Path) -> None:
    """end_line past EOF still works — clamped to last line."""
    (tmp_path / "f.py").write_text("a\nb\n")
    call = ToolCall(
        name="write_file",
        body='{"path": "f.py", "content": "Z\\n", "start_line": 2, "end_line": 99}',
    )
    result = await execute(call, tmp_path)
    assert result.ok is True
    assert (tmp_path / "f.py").read_text() == "a\nZ\n"


@pytest.mark.asyncio
async def test_write_file_content_without_trailing_newline_appends_one(tmp_path: Path) -> None:
    """Insert/replace modes — `content` without a trailing \\n still
    produces a well-formed file. Overwrite mode preserves the raw content."""
    (tmp_path / "f.py").write_text("a\nb\n")
    call = ToolCall(
        name="write_file",
        body='{"path": "f.py", "content": "X", "insert_after_line": 1}',
    )
    result = await execute(call, tmp_path)
    assert result.ok is True
    assert (tmp_path / "f.py").read_text() == "a\nX\nb\n"
