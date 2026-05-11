"""Unit tests for ToolUseCard — the inline collapsible that surfaces every
read_file / grep / run_tests invocation in the chat log."""

from __future__ import annotations

import json

from rich.syntax import Syntax

from code_scalpel.tools.agent_tools import ToolCall, ToolResult
from code_scalpel.tui.widgets.tool_use import ToolUseCard


def _card(name: str, body: dict[str, object] | str, output: str, ok: bool = True) -> ToolUseCard:
    raw = body if isinstance(body, str) else json.dumps(body)
    call = ToolCall(name=name, body=raw)
    return ToolUseCard(call, ToolResult(call=call, output=output, ok=ok))


# ── title ────────────────────────────────────────────────────────────────────


def test_title_shows_name_args_and_summary() -> None:
    card = _card("read_file", {"path": "app.py"}, "line1\nline2\nline3\n")
    title = card._title()
    assert "read_file" in title
    assert "app.py" in title
    # 3 newlines in "line1\nline2\nline3\n" → 3 (count('\n') == 3)
    assert "3 lines" in title


def test_title_failed_call_uses_red_status_dot() -> None:
    card = _card("read_file", {"path": "missing.py"}, "ENOENT", ok=False)
    title = card._title()
    # Failure summary surfaces the first line of the error
    assert "failed" in title
    assert "ENOENT" in title


def test_title_truncates_long_args() -> None:
    long_path = "a" * 120
    card = _card("read_file", {"path": long_path}, "")
    title = card._title()
    assert "…" in title
    # No raw 120-char run lingers in the title
    assert long_path not in title


# ── per-tool summary heuristics ──────────────────────────────────────────────


def test_grep_summary_counts_matches() -> None:
    card = _card("grep", {"pattern": "foo"}, "a.py:1: foo\nb.py:4: foo\nc.py:7: foo\n")
    assert "3 matches" in card._title()


def test_grep_summary_no_matches_phrase() -> None:
    card = _card("grep", {"pattern": "nope"}, "no matches found")
    assert "no matches" in card._title()


def test_run_tests_summary_first_line() -> None:
    card = _card("run_tests", "{}", "5 passed in 0.42s\n... details ...\n")
    assert "5 passed" in card._title()


# ── preview / truncation ─────────────────────────────────────────────────────


def test_preview_short_output_returned_whole() -> None:
    card = _card("grep", {"pattern": "x"}, "a\nb\nc")
    head, hidden = card._preview_text()
    assert head == "a\nb\nc"
    assert hidden == 0


def test_preview_long_output_truncates_with_hidden_count() -> None:
    lines = "\n".join(f"line {i}" for i in range(1, 21))  # 20 lines
    card = _card("grep", {"pattern": "x"}, lines)
    head, hidden = card._preview_text()
    # _PREVIEW_LINES is 5
    assert head.count("\n") == 4  # 5 lines → 4 newlines between them
    assert hidden == 15


def test_preview_full_mode_skips_truncation() -> None:
    """`full=True` short-circuits the cap — for cards whose body is small
    by construction (e.g. /stats: 6-10 rows of session metadata), the
    "N more lines (Ctrl+O for full view)" footer is pure noise."""
    lines = "\n".join(f"line {i}" for i in range(1, 21))  # 20 lines, > preview
    call = ToolCall(name="session_stats", body="")
    card = ToolUseCard(call, ToolResult(call=call, output=lines, ok=True), full=True)
    head, hidden = card._preview_text()
    assert head == lines  # the whole thing
    assert hidden == 0


# ── syntax highlighting (read_file only) ─────────────────────────────────────


def test_read_file_python_gets_syntax_renderable() -> None:
    card = _card("read_file", {"path": "x.py"}, "def f():\n    return 1\n")
    rend = card._preview_renderable()
    assert isinstance(rend, Syntax)
    assert rend.lexer is not None
    assert rend.lexer.name == "Python"


def test_read_file_typescript_recognised() -> None:
    card = _card("read_file", {"path": "src/app.tsx"}, "const x = 1;\n")
    rend = card._preview_renderable()
    assert isinstance(rend, Syntax)
    assert rend.lexer is not None
    assert rend.lexer.name == "TSX"


def test_read_file_unknown_extension_falls_back_to_plain() -> None:
    card = _card("read_file", {"path": "weird.xyz"}, "blob")
    rend = card._preview_renderable()
    # No lexer for .xyz — preview must stay plain text, not crash.
    assert not isinstance(rend, Syntax)


def test_read_file_failure_skips_highlighting() -> None:
    """Error message isn't valid source — don't try to color it."""
    card = _card("read_file", {"path": "x.py"}, "permission denied", ok=False)
    rend = card._preview_renderable()
    assert not isinstance(rend, Syntax)


def test_grep_output_not_highlighted_even_if_args_have_path() -> None:
    """Syntax highlight is read_file-only; grep results are pattern matches,
    not source code, so don't run them through Pygments."""
    card = _card("grep", {"pattern": "foo", "path": "x.py"}, "x.py:1: foo bar\n")
    rend = card._preview_renderable()
    assert not isinstance(rend, Syntax)


def test_malformed_read_file_body_does_not_crash() -> None:
    """If the model emits non-JSON arguments (shouldn't happen with native
    function calling, but be defensive), fall back to plain text — no
    lexer lookup, no exception."""
    card = _card("read_file", "this is not json", "def x(): pass")
    rend = card._preview_renderable()
    assert not isinstance(rend, Syntax)
