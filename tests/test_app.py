"""Headless tests for ScalpelApp — slash commands, ESC cancellation, layout."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from code_scalpel.agent import StepAgent
from code_scalpel.config import AgentConfig, AppConfig, ModelProfile
from code_scalpel.llm.adapter import ChatResponse, StreamChunk
from code_scalpel.tui.app import ScalpelApp
from code_scalpel.tui.widgets.input import ModeInput
from code_scalpel.tui.widgets.output import OutputLog

_CONFIG = AppConfig(
    profiles={"local": ModelProfile(provider="lmstudio", model="local-model")},
    agent=AgentConfig(max_files=0, max_file_lines=10),
)


class _StreamingMock:
    """LLM mock with controllable stream pacing — lets tests interrupt mid-stream."""

    def __init__(self, chunks: list[str], delay: float = 0.0) -> None:
        self._chunks = chunks
        self._delay = delay
        self.calls: list[list[dict[str, str]]] = []

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,  # noqa: ARG002
        **kwargs: Any,
    ) -> ChatResponse:
        self.calls.append(messages)
        content = "".join(self._chunks)
        return ChatResponse(content=content, prompt_tokens=0, completion_tokens=0, cost=None)

    async def stream(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,  # noqa: ARG002
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        self.calls.append(messages)
        for chunk in self._chunks:
            if self._delay:
                await asyncio.sleep(self._delay)
            yield StreamChunk(text=chunk)


def _attach_mock(app: ScalpelApp, mock: _StreamingMock) -> None:
    app._agent = StepAgent(llm=mock, cwd=app.cwd, config=app.config)


@pytest.fixture
def sandbox(tmp_path: Path) -> Path:
    (tmp_path / "hello.py").write_text("x = 1\n")
    return tmp_path


@pytest.mark.asyncio
async def test_app_starts_with_input_focused(sandbox: Path) -> None:
    app = ScalpelApp(config=_CONFIG, cwd=sandbox)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        assert app.focused is not None
        assert app.focused.__class__.__name__ == "Input"


@pytest.mark.asyncio
async def test_app_layout_has_separator_rules(sandbox: Path) -> None:
    app = ScalpelApp(config=_CONFIG, cwd=sandbox)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        rules = list(app.query("Rule.input-rule"))
        assert len(rules) == 2


@pytest.mark.asyncio
async def test_output_log_has_spacer_for_bottom_anchored_chat(sandbox: Path) -> None:
    app = ScalpelApp(config=_CONFIG, cwd=sandbox)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        output = app.query_one(OutputLog)
        spacers = [c for c in output.children if c.id == "_spacer"]
        assert len(spacers) == 1


@pytest.mark.asyncio
async def test_slash_new_clears_chat(sandbox: Path) -> None:
    app = ScalpelApp(config=_CONFIG, cwd=sandbox)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        _attach_mock(app, _StreamingMock(["hello"]))
        output = app.query_one(OutputLog)

        # post a regular message
        app.post_message_no_wait_substitute = None  # type: ignore[attr-defined]
        app._handle_slash("/help")  # appends a status line
        await pilot.pause(0.1)
        assert len([c for c in output.children if c.id != "_spacer"]) >= 1

        app._handle_slash("/new")
        await pilot.pause(0.1)
        # /new wipes everything but the spacer
        assert [c.id for c in output.children] == ["_spacer"]


@pytest.mark.asyncio
async def test_slash_mode_switches_mode(sandbox: Path) -> None:
    app = ScalpelApp(config=_CONFIG, cwd=sandbox)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        assert app.query_one(ModeInput).mode == "ask"
        app._handle_slash("/mode plan")
        await pilot.pause(0.05)
        assert app.query_one(ModeInput).mode == "plan"


@pytest.mark.asyncio
async def test_mode_switch_updates_cursor_class(sandbox: Path) -> None:
    """Cursor cell must repaint to match the new mode (gold for plan, etc.).
    We check the CSS class — the actual repaint is Textual's job."""
    app = ScalpelApp(config=_CONFIG, cwd=sandbox)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        mi = app.query_one(ModeInput)
        assert mi.has_class("mode-ask")
        app._handle_slash("/mode plan")
        await pilot.pause(0.05)
        assert mi.has_class("mode-plan")
        assert not mi.has_class("mode-ask")
        app._handle_slash("/mode code")
        await pilot.pause(0.05)
        assert mi.has_class("mode-code")
        assert not mi.has_class("mode-plan")


@pytest.mark.asyncio
async def test_slash_map_prints_project_map(sandbox: Path) -> None:
    """The user can't see the map otherwise — /map dumps it into the chat
    so you can tell exactly what context the model gets each turn."""
    # Add a recognisable symbol so we can verify the map renders it.
    (sandbox / "marker.py").write_text("def unique_marker():\n    return 42\n")

    app = ScalpelApp(config=_CONFIG, cwd=sandbox)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        output = app.query_one(OutputLog)
        before = [c.id for c in output.children]

        app._handle_slash("/map")
        await pilot.pause(0.1)

        added = [c for c in output.children if c.id not in before]
        assert added, "expected /map to mount a new output widget"
        rendered = "\n".join(str(c.render()) for c in added)
        assert "Project map" in rendered
        assert "marker.py" in rendered
        assert "def unique_marker" in rendered


@pytest.mark.asyncio
async def test_slash_help_lists_commands(sandbox: Path) -> None:
    app = ScalpelApp(config=_CONFIG, cwd=sandbox)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        output = app.query_one(OutputLog)
        before = len(list(output.children))
        app._handle_slash("/help")
        await pilot.pause(0.1)
        # one new Static appears with the commands listing
        assert len(list(output.children)) == before + 1


@pytest.mark.asyncio
async def test_resume_notice_shown_when_dirty_patch(sandbox: Path) -> None:
    """If the previous session was interrupted with dirty_patch=True, the user
    must see an inline notice on startup — and the flag should auto-clear so
    we don't nag them every launch."""
    from code_scalpel.state import AgentState

    # Set the flag as if the previous session died mid-apply
    pre = AgentState(dirty_patch=True)
    pre.save(sandbox)

    app = ScalpelApp(config=_CONFIG, cwd=sandbox)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.3)
        # Flag must be cleared so we don't keep nagging
        assert app.state.dirty_patch is False
        # Confirm a notice widget was mounted in the output area
        output = app.query_one(OutputLog)
        msg_widgets = [c for c in output.children if c.id != "_spacer"]
        assert len(msg_widgets) >= 1, "expected an inline resume notice"


@pytest.mark.asyncio
async def test_slash_command_does_not_pin_language(sandbox: Path) -> None:
    """Slash commands like '/mode plan' are not natural-language input.
    Detecting language from them would pin English even if the user is
    typing Russian for the actual conversation."""
    from code_scalpel.tui.widgets.input import UserMessage

    app = ScalpelApp(config=_CONFIG, cwd=sandbox)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        app.post_message(UserMessage("/mode plan"))
        await pilot.pause(0.1)
        assert app.session.user_language is None


@pytest.mark.asyncio
async def test_escape_cancels_streaming_worker(sandbox: Path) -> None:
    app = ScalpelApp(config=_CONFIG, cwd=sandbox)
    # 50 small chunks with a tiny delay each → roughly 100ms total
    mock = _StreamingMock(["x"] * 50, delay=0.002)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        _attach_mock(app, mock)

        # trigger a streaming response via the message channel
        from code_scalpel.tui.widgets.input import UserMessage

        app.post_message(UserMessage("hi"))
        await pilot.pause(0.05)  # let a few chunks stream
        await pilot.press("escape")
        await pilot.pause(0.2)

        worker = getattr(app, "_step_worker", None)
        assert worker is not None
        assert worker.is_cancelled or worker.is_finished


def test_format_step_status_no_tools_shows_warning() -> None:
    from code_scalpel.tui.app import _format_step_status

    assert _format_step_status(0, 0.0) == "● idle · [yellow]⚠ no tools used[/yellow]"
    assert _format_step_status(0, 5.4) == "● idle · [yellow]⚠ no tools used[/yellow] · 5 tok/s"


def test_format_step_status_pluralises_tool_noun() -> None:
    from code_scalpel.tui.app import _format_step_status

    # 1 → singular ("1 tool"); 2+ → plural ("2 tools")
    assert _format_step_status(1, 0.0) == "● idle · 🔧 1 tool"
    assert _format_step_status(2, 0.0) == "● idle · 🔧 2 tools"
    assert _format_step_status(5, 8.7) == "● idle · 🔧 5 tools · 9 tok/s"


@pytest.mark.asyncio
async def test_footer_flags_when_model_used_no_tools(sandbox: Path) -> None:
    """The reply was generated without any read_file/grep — show a warning
    in the footer so the user can spot the kind of answer the screenshot
    bug produced ('summary_line() exists, trust me')."""
    from code_scalpel.tui.widgets.footer import StatusFooter
    from code_scalpel.tui.widgets.input import UserMessage

    app = ScalpelApp(config=_CONFIG, cwd=sandbox)
    mock = _StreamingMock(["plain reply, no tools"])
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        _attach_mock(app, mock)

        app.post_message(UserMessage("hi"))
        # Let stream finish — short content, no delay.
        await pilot.pause(0.3)

        status = app.query_one(StatusFooter).status
        assert "no tools used" in status, f"footer didn't flag ungrounded reply: {status!r}"


@pytest.mark.asyncio
async def test_footer_model_reactive_renders(sandbox: Path) -> None:
    """When model is set, footer must include it in the rendered label.
    Empty model means no dim suffix — keep the bar tidy for legacy configs."""
    from textual.widgets import Label

    from code_scalpel.tui.widgets.footer import StatusFooter

    app = ScalpelApp(config=_CONFIG, cwd=sandbox)
    async with app.run_test(headless=True, size=(120, 24)) as pilot:
        await pilot.pause(0.1)
        footer = app.query_one(StatusFooter)
        label = footer.query_one("#footer-label", Label)

        # Without a model set the label has no dim trailing chunk.
        assert "dim" not in str(label.render())

        footer.model = "qwen2.5-coder-14b"
        await pilot.pause(0.05)
        rendered = str(label.render())
        assert "qwen2.5-coder-14b" in rendered
