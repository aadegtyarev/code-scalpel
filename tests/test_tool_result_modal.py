"""Tests for ToolResultModal — the Ctrl+O full-result viewer.

Plan §v0.3 hook: ToolUseCard inline shows only 5 lines; this modal lets
the user see the rest with syntax highlighting, without choking the chat
log on 200-line files.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from rich.syntax import Syntax

from code_scalpel.tools.agent_tools import ToolCall, ToolResult
from code_scalpel.tui.widgets.tool_result_modal import ToolResultModal


def _result(name: str, body: dict[str, object] | str, output: str, ok: bool = True) -> ToolResult:
    raw = body if isinstance(body, str) else json.dumps(body)
    call = ToolCall(name=name, body=raw)
    return ToolResult(call=call, output=output, ok=ok)


def test_header_reports_status_and_dimensions() -> None:
    modal = ToolResultModal(_result("read_file", {"path": "x.py"}, "a\nb\nc\n"))
    header = modal._header_text()
    assert "read_file" in header
    assert "x.py" in header
    # 3 lines (splitlines drops trailing \n) + char count
    assert "3 lines" in header
    assert "6 chars" in header
    assert "ok" in header


def test_header_failed_call_shows_failed_state() -> None:
    modal = ToolResultModal(_result("read_file", {"path": "n.py"}, "boom", ok=False))
    header = modal._header_text()
    assert "failed" in header


def test_body_read_file_python_is_syntax_highlighted() -> None:
    modal = ToolResultModal(_result("read_file", {"path": "x.py"}, "def f(): pass\n"))
    body = modal._body_renderable()
    assert isinstance(body, Syntax)
    assert body.lexer is not None
    assert body.lexer.name == "Python"


def test_body_failed_call_skips_highlighting() -> None:
    """Error messages aren't source — render as plain text."""
    modal = ToolResultModal(_result("read_file", {"path": "x.py"}, "ENOENT", ok=False))
    body = modal._body_renderable()
    assert not isinstance(body, Syntax)


def test_body_non_read_file_tools_render_plain() -> None:
    modal = ToolResultModal(_result("grep", {"pattern": "x"}, "a.py:1: x\n"))
    body = modal._body_renderable()
    assert not isinstance(body, Syntax)


def test_body_empty_output_shows_placeholder() -> None:
    modal = ToolResultModal(_result("grep", {"pattern": "x"}, ""))
    body = modal._body_renderable()
    # Empty result must still render something — not literally empty.
    assert isinstance(body, str)
    assert "empty" in body


# ── integration via the running app ──────────────────────────────────────────


_PROJECT_CONFIG_IMPORT = """\
from code_scalpel.config import AgentConfig, AppConfig, ModelProfile
_CFG = AppConfig(
    profiles={"local": ModelProfile(provider="lmstudio", model="local-model")},
    agent=AgentConfig(max_files=0, max_file_lines=10),
)
"""


@pytest.fixture
def sandbox(tmp_path: Path) -> Path:
    (tmp_path / "hello.py").write_text("x = 1\n")
    return tmp_path


@pytest.mark.asyncio
async def test_ctrl_o_with_no_tool_result_prints_hint(sandbox: Path) -> None:
    """Pressing Ctrl+O before any tool ran should not crash and should
    surface a notice in the chat — silent failure would feel like a bug."""
    from code_scalpel.config import AgentConfig, AppConfig, ModelProfile
    from code_scalpel.tui.app import ScalpelApp
    from code_scalpel.tui.widgets.output import OutputLog

    cfg = AppConfig(
        profiles={"local": ModelProfile(provider="lmstudio", model="local-model")},
        agent=AgentConfig(max_files=0, max_file_lines=10),
    )
    app = ScalpelApp(config=cfg, cwd=sandbox)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        app.action_show_last_tool_result()
        await pilot.pause(0.05)
        output = app.query_one(OutputLog)
        text = "\n".join(str(c.render()) for c in output.children if c.id != "_spacer")
        assert "No tool result" in text


@pytest.mark.asyncio
async def test_ctrl_o_opens_modal_after_tool_call(sandbox: Path) -> None:
    """After a tool result is recorded, Ctrl+O pushes ToolResultModal."""
    from code_scalpel.config import AgentConfig, AppConfig, ModelProfile
    from code_scalpel.tui.app import ScalpelApp

    cfg = AppConfig(
        profiles={"local": ModelProfile(provider="lmstudio", model="local-model")},
        agent=AgentConfig(max_files=0, max_file_lines=10),
    )
    app = ScalpelApp(config=cfg, cwd=sandbox)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        # Pretend a tool round-trip happened.
        app._last_tool_result = _result("read_file", {"path": "hello.py"}, "x = 1\n")
        app.action_show_last_tool_result()
        await pilot.pause(0.1)
        # Modal is now the active screen on top of the stack.
        assert isinstance(app.screen, ToolResultModal)
        # Escape closes it.
        await pilot.press("escape")
        await pilot.pause(0.1)
        assert not isinstance(app.screen, ToolResultModal)
