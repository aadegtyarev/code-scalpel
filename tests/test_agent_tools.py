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
async def test_map_file_rejects_missing_path(tmp_path: Path) -> None:
    call = ToolCall(name="map_file", body="")
    result = await execute(call, tmp_path)
    assert not result.ok
    assert "missing" in result.output


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


@pytest.mark.asyncio
async def test_run_tests_reports_failure(tmp_path: Path) -> None:
    (tmp_path / "test_x.py").write_text("def test_a(): assert 1 == 2\n")
    call = ToolCall(name="run_tests", body="")
    result = await execute(call, tmp_path)
    assert not result.ok
    assert "exit code:" in result.output
    assert "1" in result.output  # non-zero exit code


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
