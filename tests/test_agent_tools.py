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
