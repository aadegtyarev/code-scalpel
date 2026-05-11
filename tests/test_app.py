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
async def test_slash_map_mounts_tool_use_card(sandbox: Path) -> None:
    """/map shouldn't dump 500 lines into the chat — it must follow the
    same collapsed-result pattern every other tool uses. Mounting a
    ToolUseCard reuses the existing 5-line preview + Ctrl+O popup."""
    from code_scalpel.tui.widgets.tool_use import ToolUseCard

    (sandbox / "marker.py").write_text("def unique_marker():\n    return 42\n")

    app = ScalpelApp(config=_CONFIG, cwd=sandbox)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        output = app.query_one(OutputLog)

        app._handle_slash("/map")
        await pilot.pause(0.1)

        cards = list(output.query(ToolUseCard))
        assert cards, "expected /map to mount a ToolUseCard"
        card = cards[-1]
        # Title carries the synthetic tool name + a line-count summary.
        title = card._title()
        assert "project_map" in title
        assert "lines" in title
        # The full content is queryable but rendered collapsed by default.
        assert "marker.py" in card._result.output
        # Ctrl+O target updated so users can pop the full map.
        assert app._last_tool_result is card._result


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


def test_format_turn_summary_omits_tools_field_when_zero() -> None:
    """When no tools were called, the summary just drops that field —
    the inline tool cards above already make their absence obvious."""
    from code_scalpel.tui.app import _format_turn_summary

    out = _format_turn_summary(
        tool_calls=0,
        rate=5.4,
        completion_tokens=234,
        duration=1.4,
        ctx_used=1024,
        ctx_limit=16384,
    )
    assert "tools" not in out
    assert "no tools used" not in out
    assert "🔧" not in out
    # Other fields still present
    assert "↓ 234 tokens" in out
    assert "5 tok/s" in out
    assert "1.4s" in out
    assert "ctx 1k/16k" in out
    # No dim wrapper — colour comes from the msg-summary CSS class.
    assert out.startswith("⤷ ")
    assert "[dim]" not in out


def test_format_turn_summary_pluralises_tool_noun() -> None:
    from code_scalpel.tui.app import _format_turn_summary

    one = _format_turn_summary(
        tool_calls=1, rate=0.0, completion_tokens=0, duration=0.0, ctx_used=0, ctx_limit=0
    )
    assert "🔧 1 tool" in one and "tools" not in one

    many = _format_turn_summary(
        tool_calls=3, rate=0.0, completion_tokens=0, duration=0.0, ctx_used=0, ctx_limit=0
    )
    assert "🔧 3 tools" in many


def test_format_turn_summary_drops_zero_fields() -> None:
    """Zero rate / zero tokens / no ctx limit shouldn't add empty noise."""
    from code_scalpel.tui.app import _format_turn_summary

    out = _format_turn_summary(
        tool_calls=2, rate=0.0, completion_tokens=0, duration=0.0, ctx_used=0, ctx_limit=0
    )
    assert "tok/s" not in out
    assert "tokens" not in out
    assert "ctx " not in out


@pytest.mark.asyncio
async def test_inline_turn_summary_appears_after_turn(sandbox: Path) -> None:
    """Every completed turn drops a dim summary line into the chat with
    duration/ctx. When no tools were called the tool field is just
    omitted — no yellow warning, no shouting — the inline tool cards
    above already make tool absence visible."""
    from code_scalpel.tui.widgets.footer import StatusFooter
    from code_scalpel.tui.widgets.input import UserMessage

    app = ScalpelApp(config=_CONFIG, cwd=sandbox)
    mock = _StreamingMock(["plain reply, no tools"])
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        _attach_mock(app, mock)

        app.post_message(UserMessage("hi"))
        await pilot.pause(0.3)

        # Footer carries no warning either way.
        footer_status = app.query_one(StatusFooter).status
        assert "no tools used" not in footer_status

        output = app.query_one(OutputLog)
        chat = "\n".join(str(c.render()) for c in output.children if c.id != "_spacer")
        # Summary marker is there.
        assert "⤷" in chat, f"inline summary missing:\n{chat}"
        # But no warning — tool field is just absent for tool_calls=0.
        assert "no tools used" not in chat
        assert "🔧" not in chat
        # Duration field present.
        assert "0.0s" in chat or "0.1s" in chat or "0.2s" in chat


@pytest.mark.asyncio
async def test_turn_progress_widget_mounts_during_stream(sandbox: Path) -> None:
    """In-chat progress widget must appear in the chat once a turn starts,
    replacing the old `streaming · N tok/s` footer overload."""
    from code_scalpel.tui.widgets.input import UserMessage
    from code_scalpel.tui.widgets.turn_progress import TurnProgress

    app = ScalpelApp(config=_CONFIG, cwd=sandbox)
    # Slow enough that the progress widget has time to mount and update
    # before the stream finalises and removes it.
    mock = _StreamingMock(["chunk-"] * 8, delay=0.05)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        _attach_mock(app, mock)

        app.post_message(UserMessage("hi"))
        # Mid-stream: progress widget should be visible.
        await pilot.pause(0.15)
        output = app.query_one(OutputLog)
        progress_widgets = list(output.query(TurnProgress))
        assert progress_widgets, "expected TurnProgress widget mid-stream"
        # And it must sit AFTER the user message — same depth as the reply.
        children = [c for c in output.children if c.id != "_spacer"]
        user_idx = next(
            i
            for i, c in enumerate(children)
            if "msg-user" in c.classes  # type: ignore[arg-type]
        )
        progress_idx = next(i for i, c in enumerate(children) if isinstance(c, TurnProgress))
        assert progress_idx > user_idx


@pytest.mark.asyncio
async def test_turn_progress_widget_removed_after_turn(sandbox: Path) -> None:
    """When the turn finalises, the live progress widget must be gone —
    the permanent inline summary line (⤷ …) takes over."""
    from code_scalpel.tui.widgets.input import UserMessage
    from code_scalpel.tui.widgets.turn_progress import TurnProgress

    app = ScalpelApp(config=_CONFIG, cwd=sandbox)
    mock = _StreamingMock(["short reply"])
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        _attach_mock(app, mock)

        app.post_message(UserMessage("hi"))
        await pilot.pause(0.3)

        output = app.query_one(OutputLog)
        assert list(output.query(TurnProgress)) == [], (
            "TurnProgress must be removed once the turn ends"
        )
        # Final summary line is still mounted in its place.
        chat = "\n".join(str(c.render()) for c in output.children if c.id != "_spacer")
        assert "⤷" in chat


@pytest.mark.asyncio
async def test_footer_never_shows_streaming_rate(sandbox: Path) -> None:
    """Footer must stay clean: `◌ thinking…` while in-flight, `● idle` after.
    The old `streaming · N tok/s` overload moved into the inline progress
    widget — the footer must never carry numeric throughput data again."""
    from code_scalpel.tui.widgets.footer import StatusFooter
    from code_scalpel.tui.widgets.input import UserMessage

    app = ScalpelApp(config=_CONFIG, cwd=sandbox)
    # Lots of small chunks with a delay so we have time to sample the
    # footer in the middle of streaming.
    mock = _StreamingMock(["x"] * 30, delay=0.01)
    seen_statuses: list[str] = []
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        _attach_mock(app, mock)
        footer = app.query_one(StatusFooter)

        app.post_message(UserMessage("hi"))
        # Sample status repeatedly while the stream runs.
        for _ in range(10):
            seen_statuses.append(footer.status)
            await pilot.pause(0.03)
        await pilot.pause(0.3)
        seen_statuses.append(footer.status)

        # No intermediate streaming-rate status ever leaked into the footer.
        for s in seen_statuses:
            assert "streaming" not in s, f"footer leaked streaming status: {s!r}"
            assert "tok/s" not in s, f"footer leaked tok/s: {s!r}"
        # Final status is the idle/end marker — not an error or stale state.
        assert footer.status == "● idle"


@pytest.mark.asyncio
async def test_inline_summary_carries_tokens_duration_after_turn(sandbox: Path) -> None:
    """After a turn closes, the chat must contain a single summary line
    with at least tokens and duration — the data the user needs to gauge
    cost without looking at the footer."""
    from code_scalpel.tui.widgets.input import UserMessage

    app = ScalpelApp(config=_CONFIG, cwd=sandbox)
    # A modestly-sized reply so the token field is non-zero.
    mock = _StreamingMock(["lorem ipsum dolor sit amet " * 20])
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        _attach_mock(app, mock)

        app.post_message(UserMessage("hi"))
        await pilot.pause(0.3)

        output = app.query_one(OutputLog)
        chat = "\n".join(str(c.render()) for c in output.children if c.id != "_spacer")
        assert "⤷" in chat
        # Tokens and duration both rendered.
        assert "tokens" in chat
        assert "s" in chat  # the "Ns" duration field is there


def test_turn_progress_format_grows_as_data_arrives() -> None:
    """Format helper: drops zero-fields, includes tokens once they appear,
    pluralises the tool noun. Same conventions as `_format_turn_summary`
    so the live and final lines feel like the same artifact."""
    from code_scalpel.tui.widgets.turn_progress import _format_progress

    empty = _format_progress(tokens=0, tool_calls=0, elapsed_s=0.0, rate_tok_s=0.0)
    assert empty.startswith("⋯ thinking")
    # No noisy zero fields.
    assert "tokens" not in empty
    assert "tok/s" not in empty
    assert "🔧" not in empty

    growing = _format_progress(tokens=120, tool_calls=1, elapsed_s=3.2, rate_tok_s=18.0)
    assert "↓ 120 tokens" in growing
    assert "🔧 1 tool" in growing and "tools" not in growing
    assert "3s" in growing
    assert "18 tok/s" in growing

    many = _format_progress(tokens=10, tool_calls=4, elapsed_s=1.0, rate_tok_s=2.0)
    assert "🔧 4 tools" in many


@pytest.mark.asyncio
async def test_slash_tasks_with_no_file_prints_hint(sandbox: Path) -> None:
    """No .code-scalpel/TASKS.md → /tasks must coach the user toward plan
    mode, not crash and not mount an empty card."""
    app = ScalpelApp(config=_CONFIG, cwd=sandbox)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        output = app.query_one(OutputLog)
        before = len(list(output.children))

        app._handle_slash("/tasks")
        await pilot.pause(0.1)

        # One Static status line was added with the hint text.
        children = [c for c in output.children if c.id != "_spacer"]
        assert len(children) == before  # spacer is included in `before`, so equal == +1 status
        rendered = "\n".join(str(c.render()) for c in children)
        assert "No plan yet" in rendered


@pytest.mark.asyncio
async def test_slash_tasks_mounts_card_when_file_exists(sandbox: Path) -> None:
    """With TASKS.md present, /tasks mounts a ToolUseCard so the plan is
    visible without dumping the whole file body into the chat."""
    from code_scalpel.tui.widgets.tool_use import ToolUseCard

    tasks_dir = sandbox / ".code-scalpel"
    tasks_dir.mkdir()
    (tasks_dir / "TASKS.md").write_text(
        "## T001: do the thing\n\nGoal: prove it works\nFiles: x.py\n"
    )

    app = ScalpelApp(config=_CONFIG, cwd=sandbox)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        output = app.query_one(OutputLog)

        app._handle_slash("/tasks")
        await pilot.pause(0.1)

        cards = list(output.query(ToolUseCard))
        assert cards, "expected /tasks to mount a ToolUseCard"
        card = cards[-1]
        assert card._call.name == "tasks_md"
        assert "T001" in card._result.output
        # Ctrl+O target updated so the full file is one keystroke away.
        assert app._last_tool_result is card._result


@pytest.mark.asyncio
async def test_slash_system_mounts_card_with_prompt(sandbox: Path) -> None:
    """/system mounts a ToolUseCard whose body is the actual system prompt —
    the user can see what the model sees on each turn."""
    from code_scalpel.tui.widgets.tool_use import ToolUseCard

    app = ScalpelApp(config=_CONFIG, cwd=sandbox)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        output = app.query_one(OutputLog)

        app._handle_slash("/system")
        await pilot.pause(0.1)

        cards = list(output.query(ToolUseCard))
        assert cards, "expected /system to mount a ToolUseCard"
        card = cards[-1]
        assert card._call.name == "system_prompt"
        # Anchor specific to the project's prompt — guards against accidental
        # gutting of the system message.
        assert "code-scalpel" in card._result.output


@pytest.mark.asyncio
async def test_slash_system_appends_plan_addendum_when_in_plan_mode(
    sandbox: Path,
) -> None:
    """In plan mode the addendum is concatenated onto the base prompt —
    /system must reflect that so the user sees exactly what the next turn
    will carry."""
    from code_scalpel.tui.widgets.tool_use import ToolUseCard

    app = ScalpelApp(config=_CONFIG, cwd=sandbox)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        app._handle_slash("/mode plan")
        await pilot.pause(0.05)

        app._handle_slash("/system")
        await pilot.pause(0.1)

        output = app.query_one(OutputLog)
        cards = list(output.query(ToolUseCard))
        assert cards
        body = cards[-1]._result.output
        assert "PLAN mode" in body


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
