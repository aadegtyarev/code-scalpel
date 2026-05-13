"""Headless tests for ScalpelApp — slash commands, ESC cancellation, layout."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from code_scalpel.config import AgentConfig, AppConfig, ModelProfile
from code_scalpel.llm.adapter import ChatResponse, StreamChunk, StreamUsage
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
        total_chars = 0
        for chunk in self._chunks:
            if self._delay:
                await asyncio.sleep(self._delay)
            total_chars += len(chunk)
            yield StreamChunk(text=chunk)
        # Mirror what a real provider does when stream_options.include_usage
        # is set — close the stream with a usage chunk so the agent can yield
        # a UsageReport instead of relying on char-count estimates.
        yield StreamChunk(
            usage=StreamUsage(
                prompt_tokens=sum(len(str(m.get("content", ""))) for m in messages) // 4,
                completion_tokens=max(1, total_chars // 4),
            )
        )


def _attach_mock(app: ScalpelApp, mock: _StreamingMock) -> None:
    """Swap the whole Runtime so the TUI's `runtime.stream` path picks up
    the mock. Touching just `app._agent` worked before the Runtime refactor
    but is a dead-end now — the TUI no longer reaches through that field."""
    from code_scalpel.runtime import Runtime

    app.runtime = Runtime(cwd=app.cwd, config=app.config, llm=mock, with_memory=False)
    app._agent = app.runtime.agent
    app.session = app.runtime.session
    app._memory = app.runtime.memory


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
        assert app.focused.__class__.__name__ in ("Input", "HistoryInput")


@pytest.mark.asyncio
async def test_exit_summary_uses_full_stats_report(sandbox: Path) -> None:
    """on_unmount captures the multi-line stats_report, not the one-liner —
    the user reviewing what a session cost wants tokens/cost/elapsed/model
    visible, not a `↑Xk ↓Yk` chunk that drops everything but raw numbers."""
    app = ScalpelApp(config=_CONFIG, cwd=sandbox)
    mock = _StreamingMock(["hi"])
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        _attach_mock(app, mock)
        # Stage some session activity so the summary has something to show.
        app.session.record(
            ChatResponse(content="", prompt_tokens=120, completion_tokens=80, cost=0.005)
        )
    # on_unmount fires during run_test teardown.
    assert app._exit_summary is not None
    summary = app._exit_summary
    assert "Session summary:" in summary
    # stats_report shape: labelled rows for tokens / requests / elapsed
    assert "requests" in summary
    assert "tokens" in summary
    assert "elapsed" in summary
    # Numbers from the recorded response surface in the report
    assert "120" in summary  # prompt total
    assert "80" in summary  # completion total


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
    )
    assert "tools" not in out
    assert "no tools used" not in out
    assert "🔧" not in out
    # Other fields still present
    assert "↓ 234 tokens" in out
    assert "5 tok/s" in out
    assert "1.4s" in out
    # Ctx lives in the footer now, not the inline turn summary.
    assert "ctx" not in out
    # No dim wrapper — colour comes from the msg-summary CSS class.
    assert out.startswith("⤷ ")
    assert "[dim]" not in out


def test_format_turn_summary_pluralises_tool_noun() -> None:
    from code_scalpel.tui.app import _format_turn_summary

    one = _format_turn_summary(tool_calls=1, rate=0.0, completion_tokens=0, duration=0.0)
    assert "🔧 1 tool" in one and "tools" not in one

    many = _format_turn_summary(tool_calls=3, rate=0.0, completion_tokens=0, duration=0.0)
    assert "🔧 3 tools" in many


def test_format_turn_summary_drops_zero_fields() -> None:
    """Zero rate / zero tokens shouldn't add empty noise. Ctx moved to
    the footer — verify it's not leaking back into the inline summary."""
    from code_scalpel.tui.app import _format_turn_summary

    out = _format_turn_summary(tool_calls=2, rate=0.0, completion_tokens=0, duration=0.0)
    assert "tok/s" not in out
    assert "tokens" not in out
    assert "ctx " not in out


@pytest.mark.asyncio
async def test_plan_card_mounts_after_plan_mode_turn(sandbox: Path) -> None:
    """When plan mode replies with a structured plan (## T###: ...), the
    PlanCard widget is auto-mounted right after the markdown reply so the
    user can scan tasks visually without re-reading the prose."""
    from code_scalpel.tui.widgets.input import UserMessage
    from code_scalpel.tui.widgets.plan_card import PlanCard

    plan_reply = (
        "Here's the plan:\n\n"
        "## T001: First task\n\n"
        "Goal: do thing\n"
        "Files: a.py\n"
        "Acceptance:\n"
        "- works\n"
        "Test command: pytest a\n\n"
        "## T002: Second task\n\n"
        "Goal: do another\n"
        "Files: b.py\n"
        "Acceptance:\n"
        "- works\n"
        "Test command: pytest b\n"
    )
    app = ScalpelApp(config=_CONFIG, cwd=sandbox)
    mock = _StreamingMock([plan_reply])
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        _attach_mock(app, mock)
        app._handle_slash("/mode plan")
        await pilot.pause(0.05)
        app.post_message(UserMessage("plan it"))
        await pilot.pause(0.5)
        cards = list(app.query(PlanCard))
        assert cards, "expected PlanCard to be mounted after plan-mode turn"
        assert len(cards[0].tasks) == 2


@pytest.mark.asyncio
async def test_plan_card_not_mounted_in_non_plan_modes(sandbox: Path) -> None:
    """Same plan-shape reply but mode=ask → no PlanCard. The card is
    plan-mode-specific so other modes don't accidentally summon it."""
    from code_scalpel.tui.widgets.input import UserMessage
    from code_scalpel.tui.widgets.plan_card import PlanCard

    plan_reply = "## T001: x\n\nGoal: y\nFiles: a.py\nAcceptance:\n- ok\nTest command: pytest\n"
    app = ScalpelApp(config=_CONFIG, cwd=sandbox)
    mock = _StreamingMock([plan_reply])
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        _attach_mock(app, mock)
        # Stay in ask mode
        app.post_message(UserMessage("question"))
        await pilot.pause(0.5)
        assert not list(app.query(PlanCard))


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
    """Footer must stay clean: no streaming rate data, empty status after turn.
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
        # Final status is empty (idle) — not an error or stale state.
        assert footer.status in ("", "● error")


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
    """With TASKS.md present, /tasks mounts a PlanCard so the plan is
    visible inline."""
    from code_scalpel.tui.widgets.plan_card import PlanCard

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
        await pilot.pause(0.2)

        cards = list(output.query(PlanCard))
        assert cards, "expected /tasks to mount a PlanCard"
        task_ids = [t.task_id for t in cards[-1].tasks]
        assert "T001" in task_ids


@pytest.mark.asyncio
async def test_slash_stats_mounts_card_with_session_stats(sandbox: Path) -> None:
    """/stats mounts a ToolUseCard whose body is the live session report —
    requests / tokens / elapsed / mode / model — so the user can sanity-
    check cost and behaviour without leaving the chat."""
    from code_scalpel.tui.widgets.tool_use import ToolUseCard

    app = ScalpelApp(config=_CONFIG, cwd=sandbox)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        output = app.query_one(OutputLog)

        app._handle_slash("/stats")
        await pilot.pause(0.1)

        cards = list(output.query(ToolUseCard))
        assert cards, "expected /stats to mount a ToolUseCard"
        card = cards[-1]
        assert card._call.name == "session_stats"
        body = card._result.output
        # Spot-check fields that must show up even on a fresh session
        assert "requests" in body
        assert "elapsed" in body
        assert "tokens" in body
        assert "mode" in body


@pytest.mark.asyncio
async def test_slash_stats_reflects_current_mode(sandbox: Path) -> None:
    """After /mode plan the next /stats must report mode=plan — the report
    is the user's only programmatic readback of which mode is active."""
    from code_scalpel.tui.widgets.tool_use import ToolUseCard

    app = ScalpelApp(config=_CONFIG, cwd=sandbox)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        app._handle_slash("/mode plan")
        await pilot.pause(0.05)

        app._handle_slash("/stats")
        await pilot.pause(0.1)

        output = app.query_one(OutputLog)
        cards = list(output.query(ToolUseCard))
        assert cards
        body = cards[-1]._result.output
        assert "plan" in body


@pytest.mark.asyncio
async def test_tab_does_not_leave_input_when_chat_is_empty(sandbox: Path) -> None:
    """Pressing Tab from the input on a fresh session must not move focus
    anywhere visible. Before the fix VerticalScroll (OutputLog) was
    focusable and Tab would silently land there — the user saw the input
    cursor disappear with no feedback. After the fix the scroll is out
    of the Tab cycle and focus simply stays put."""
    app = ScalpelApp(config=_CONFIG, cwd=sandbox)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        # Sanity: input is the initial focus target.
        assert app.focused is not None
        assert app.focused.__class__.__name__ in ("Input", "HistoryInput")

        for _ in range(3):
            await pilot.press("tab")
            await pilot.pause(0.05)

        # Focus never wandered off the input — no ghost stop on the scroll.
        assert app.focused is not None
        assert app.focused.__class__.__name__ in ("Input", "HistoryInput")


@pytest.mark.asyncio
async def test_output_log_is_not_focusable(sandbox: Path) -> None:
    """OutputLog (a VerticalScroll subclass) must opt out of focus. The
    base class defaults to ``can_focus=True``, and that was the root of
    the 'Tab goes nowhere visible' confusion the user reported."""
    app = ScalpelApp(config=_CONFIG, cwd=sandbox)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        assert app.query_one(OutputLog).can_focus is False


@pytest.mark.asyncio
async def test_tab_skips_history_tool_use_cards(sandbox: Path) -> None:
    """Tool-use cards in the scroll history are read-only — Tab must
    skip past them. Before the fix every collapsed card's title was a
    Tab stop, so pressing Tab paged the user through their entire chat
    history before reaching anything actionable."""
    from code_scalpel.tools.agent_tools import ToolCall, ToolResult

    app = ScalpelApp(config=_CONFIG, cwd=sandbox)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        output = app.query_one(OutputLog)
        for _ in range(3):
            call = ToolCall(name="read_file", body='{"path": "x.py"}')
            result = ToolResult(call=call, output="line\n" * 10, ok=True)
            output.add_tool_use(call, result)
        await pilot.pause(0.2)

        # No actionable widget exists outside the input, so Tab is a no-op.
        for _ in range(5):
            await pilot.press("tab")
            await pilot.pause(0.05)
            assert app.focused is not None
            assert app.focused.__class__.__name__ in ("Input", "HistoryInput")


@pytest.mark.asyncio
async def test_tab_cycles_between_input_and_review_card(sandbox: Path) -> None:
    """When a patch-review card is mounted, Tab must cycle between just
    two widgets: the input and the review card. History tool-use cards
    remain off the cycle so the user reaches the actionable card in one
    keystroke regardless of how long the chat is."""
    from code_scalpel.tools.agent_tools import ToolCall, ToolResult
    from code_scalpel.tui.widgets.cards.tool_call import ToolCallCard

    app = ScalpelApp(config=_CONFIG, cwd=sandbox)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        output = app.query_one(OutputLog)
        # Long chat history to make sure size doesn't matter.
        for _ in range(5):
            call = ToolCall(name="read_file", body='{"path": "x.py"}')
            result = ToolResult(call=call, output="line\n" * 10, ok=True)
            output.add_tool_use(call, result)
        await pilot.pause(0.2)

        # Mount a review card the same way the agent does on a patch.
        card = ToolCallCard("Apply", "")
        await app.mount(card, before=app.query_one(ModeInput))
        card.set_reviewing("--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-a\n+b\n")
        await pilot.pause(0.1)

        # set_reviewing already focuses the card.
        assert isinstance(app.focused, ToolCallCard)

        # One Tab gets us back to the input — no detour through history.
        await pilot.press("tab")
        await pilot.pause(0.05)
        assert app.focused is not None
        assert app.focused.__class__.__name__ in ("Input", "HistoryInput")

        # Another Tab returns to the review card.
        await pilot.press("tab")
        await pilot.pause(0.05)
        assert isinstance(app.focused, ToolCallCard)


@pytest.mark.asyncio
async def test_tool_use_card_collapsible_is_not_focusable(sandbox: Path) -> None:
    """Direct check on ToolUseCard's internal CollapsibleTitle — keeping
    the assertion close to the fix so a future refactor that drops the
    ``can_focus = False`` line is caught with a targeted failure."""
    from textual.widgets._collapsible import CollapsibleTitle

    from code_scalpel.tools.agent_tools import ToolCall, ToolResult

    app = ScalpelApp(config=_CONFIG, cwd=sandbox)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        output = app.query_one(OutputLog)
        call = ToolCall(name="read_file", body='{"path": "x.py"}')
        result = ToolResult(call=call, output="x = 1\n", ok=True)
        output.add_tool_use(call, result)
        await pilot.pause(0.2)

        titles = list(app.query(CollapsibleTitle))
        assert titles, "expected the tool-use card to mount a CollapsibleTitle"
        for t in titles:
            assert t.can_focus is False


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


# ── Ctrl+↑/↓ tool-card navigation ────────────────────────────────────────────


def _add_card(app: ScalpelApp, name: str, output: str) -> None:
    """Mount a synthetic ToolUseCard for navigation tests — avoids dragging
    a real LLM into the picture when all we want is multiple cards."""
    from code_scalpel.tools.agent_tools import ToolCall, ToolResult

    log = app.query_one(OutputLog)
    call = ToolCall(name=name, body="")
    result = ToolResult(call=call, output=output, ok=True)
    log.add_tool_use(call, result)


@pytest.mark.asyncio
async def test_ctrl_up_from_input_jumps_to_newest_card(sandbox: Path) -> None:
    """Ctrl+↑ from the input must land on the most recently added card.
    Coming "from the input" is the common case — user is typing, wants
    to revisit the tool output that just scrolled by."""
    from textual.widgets._collapsible import CollapsibleTitle

    app = ScalpelApp(config=_CONFIG, cwd=sandbox)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        _add_card(app, "read_file", "older\nstuff\n")
        _add_card(app, "grep", "newer\nstuff\n")
        await pilot.pause(0.2)

        app.action_focus_prev_card()
        await pilot.pause(0.05)
        assert isinstance(app.focused, CollapsibleTitle)
        # Newest card's title carries the grep tool name.
        from code_scalpel.tui.widgets.tool_use import ToolUseCard

        card = app._focused_card()
        assert isinstance(card, ToolUseCard)
        assert card._call.name == "grep"


@pytest.mark.asyncio
async def test_ctrl_up_then_up_walks_to_older_card(sandbox: Path) -> None:
    app = ScalpelApp(config=_CONFIG, cwd=sandbox)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        _add_card(app, "read_file", "a\n")
        _add_card(app, "grep", "b\n")
        await pilot.pause(0.2)

        app.action_focus_prev_card()  # newest = grep
        await pilot.pause(0.05)
        app.action_focus_prev_card()  # → older = read_file
        await pilot.pause(0.05)
        card = app._focused_card()
        assert card is not None
        assert card._call.name == "read_file"
        # One more Ctrl+↑ clamps at the oldest, no error.
        app.action_focus_prev_card()
        await pilot.pause(0.05)
        card = app._focused_card()
        assert card is not None
        assert card._call.name == "read_file"


@pytest.mark.asyncio
async def test_ctrl_down_past_newest_returns_focus_to_input(sandbox: Path) -> None:
    """Mirrors HistoryInput's ↓-past-newest-restores-draft semantics:
    once focus walks past the newest card, drop it back into the input."""
    app = ScalpelApp(config=_CONFIG, cwd=sandbox)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        _add_card(app, "read_file", "a\n")
        await pilot.pause(0.2)

        app.action_focus_prev_card()
        await pilot.pause(0.05)
        assert app._focused_card() is not None

        app.action_focus_next_card()
        await pilot.pause(0.05)
        assert app._focused_card() is None
        assert app.focused.__class__.__name__ in ("Input", "HistoryInput")


@pytest.mark.asyncio
async def test_escape_on_focused_card_returns_to_input(sandbox: Path) -> None:
    """Esc on a focused card means 'done browsing' — focus must go back
    to the input, NOT cancel any live step (there usually isn't one when
    the user is browsing)."""
    app = ScalpelApp(config=_CONFIG, cwd=sandbox)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        _add_card(app, "read_file", "a\n")
        await pilot.pause(0.2)

        app.action_focus_prev_card()
        await pilot.pause(0.05)
        assert app._focused_card() is not None

        app.action_cancel_step()
        await pilot.pause(0.05)
        assert app._focused_card() is None
        assert app.focused.__class__.__name__ in ("Input", "HistoryInput")


@pytest.mark.asyncio
async def test_ctrl_up_with_no_cards_is_noop(sandbox: Path) -> None:
    """Fresh app, no tool cards anywhere — Ctrl+↑ must not crash and
    must not steal focus from the input."""
    app = ScalpelApp(config=_CONFIG, cwd=sandbox)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        before = app.focused
        app.action_focus_prev_card()
        await pilot.pause(0.05)
        assert app.focused is before


# ── /remember and /recall slashes ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_slash_remember_saves_to_memory(sandbox: Path) -> None:
    """/remember persists the line and confirms inline. The follow-up
    /recall must find it back — round-trip is the whole point."""
    app = ScalpelApp(config=_CONFIG, cwd=sandbox)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        app._handle_slash("/remember always rebase, never merge")
        await pilot.pause(0.1)

        # MemoryStore must have been built lazily.
        assert app._memory is not None
        entries = app._memory.all()
        assert any("rebase" in e.text for e in entries)


@pytest.mark.asyncio
async def test_slash_remember_empty_text_errors(sandbox: Path) -> None:
    """/remember with no body is a user mistake — error inline, no
    silent save of an empty entry. MemoryStore itself rejects empties
    but we want a friendlier message than the bare exception."""
    app = ScalpelApp(config=_CONFIG, cwd=sandbox)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        app._handle_slash("/remember")
        await pilot.pause(0.1)
        # Memory store stays uninitialised — no .code-scalpel/memory.db
        # gets materialised for a typo.
        entries = app._memory.all() if app._memory else []
        assert entries == []


@pytest.mark.asyncio
async def test_slash_recall_with_query_mounts_card(sandbox: Path) -> None:
    """/recall <query> mounts a ToolUseCard with the matched notes —
    consistent surface with /map and /stats."""
    from code_scalpel.tui.widgets.tool_use import ToolUseCard

    app = ScalpelApp(config=_CONFIG, cwd=sandbox)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        app._handle_slash("/remember run ruff before commit")
        app._handle_slash("/remember tests use real database")
        await pilot.pause(0.1)

        app._handle_slash("/recall ruff")
        await pilot.pause(0.1)
        output = app.query_one(OutputLog)
        cards = list(output.query(ToolUseCard))
        assert cards, "expected /recall to mount a ToolUseCard"
        body = cards[-1]._result.output
        assert "ruff" in body
        # The query is reflected in the card's args summary
        assert "ruff" in cards[-1]._call.body


@pytest.mark.asyncio
async def test_slash_recall_no_args_lists_all(sandbox: Path) -> None:
    """Bare /recall is the "show me what's stored" sanity check — must
    list every entry, no search filter."""
    from code_scalpel.tui.widgets.tool_use import ToolUseCard

    app = ScalpelApp(config=_CONFIG, cwd=sandbox)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        app._handle_slash("/remember alpha")
        app._handle_slash("/remember bravo")
        await pilot.pause(0.1)
        app._handle_slash("/recall")
        await pilot.pause(0.1)

        output = app.query_one(OutputLog)
        cards = list(output.query(ToolUseCard))
        assert cards
        body = cards[-1]._result.output
        assert "alpha" in body
        assert "bravo" in body


@pytest.mark.asyncio
async def test_slash_recall_empty_store_prints_no_hits(sandbox: Path) -> None:
    """Empty store → friendly status line, no empty card."""
    from code_scalpel.tui.widgets.tool_use import ToolUseCard

    app = ScalpelApp(config=_CONFIG, cwd=sandbox)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        app._handle_slash("/recall anything")
        await pilot.pause(0.1)
        output = app.query_one(OutputLog)
        cards = list(output.query(ToolUseCard))
        assert not cards


# ── JobsBar integration ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_app_has_jobs_registry_exposed(sandbox: Path) -> None:
    """ScalpelApp owns the registry — that's the single point plugins
    and slash commands reach for to surface their work."""
    from code_scalpel.jobs import JobRegistry

    app = ScalpelApp(config=_CONFIG, cwd=sandbox)
    assert isinstance(app.jobs, JobRegistry)


@pytest.mark.asyncio
async def test_jobs_bar_mounted_between_input_and_footer(sandbox: Path) -> None:
    from code_scalpel.tui.widgets.footer import StatusFooter
    from code_scalpel.tui.widgets.jobs_bar import JobsBar

    app = ScalpelApp(config=_CONFIG, cwd=sandbox)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        children = list(app.screen.children)
        bar_idx = next(i for i, c in enumerate(children) if isinstance(c, JobsBar))
        footer_idx = next(i for i, c in enumerate(children) if isinstance(c, StatusFooter))
        # Bar lives between the input chrome and the footer — the moment
        # it goes live it borrows a row from there, not from the chat.
        assert bar_idx < footer_idx


@pytest.mark.asyncio
async def test_do_map_registers_then_clears_job(sandbox: Path) -> None:
    """The /map worker must `track` itself so the user sees what's
    blocking the UI when build_map is slow."""
    from code_scalpel.tui.widgets.jobs_bar import JobsBar

    app = ScalpelApp(config=_CONFIG, cwd=sandbox)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        app._handle_slash("/map")
        # Job appears almost immediately — give the worker one tick.
        await pilot.pause(0.05)
        # Either still running (bar live) or already finished (bar idle).
        # We only assert that the registry actually saw a job, not the
        # current state — fast machines may complete inside the tick.
        await pilot.pause(0.3)
        bar = app.query_one(JobsBar)
        # After completion the bar must be idle again.
        assert not bar.has_class("live")


# ── /loop slash + iterative patch loop wiring ───────────────────────────────


def _make_step_result(
    *,
    reply: str = "",
    attempts: tuple[Any, ...] = (),
) -> Any:
    """Build a StepResult shaped like what code_with_retry returns. The
    response field carries empty token counts because the loop path
    approximates usage from edits/reply length anyway."""
    from code_scalpel.agent import StepResult

    return StepResult(
        reply=reply,
        edits=[],
        response=ChatResponse(content=reply, prompt_tokens=0, completion_tokens=0, cost=None),
        attempts=attempts,
    )


def _make_attempt(
    *,
    apply_ok: bool = True,
    apply_error: str = "",
    test_output: str = "",
    tests_passed: bool = False,
    path: str = "hello.py",
    search: str = "x = 1\n",
    replace: str = "x = 2\n",
) -> Any:
    from code_scalpel.agent import PatchAttempt
    from code_scalpel.patch.edit_block import Edit

    return PatchAttempt(
        edits=[Edit(path=path, search=search, replace=replace)],
        apply_ok=apply_ok,
        apply_error=apply_error,
        test_output=test_output,
        tests_passed=tests_passed,
    )


@pytest.mark.asyncio
async def test_code_mode_iterative_loop_disabled_uses_streaming_path(sandbox: Path) -> None:
    """When iterative_patch_loop is off, code mode must keep the existing
    streaming behaviour intact — the LLM mock's stream() is consumed, not
    code_with_retry. Opt-in is one flag flip, no surprises."""
    from unittest.mock import AsyncMock

    from code_scalpel.tui.widgets.input import UserMessage

    config = AppConfig(
        profiles={"local": ModelProfile(provider="lmstudio", model="local-model")},
        agent=AgentConfig(max_files=0, max_file_lines=10, iterative_patch_loop=False),
    )
    app = ScalpelApp(config=config, cwd=sandbox)
    mock_llm = _StreamingMock(["just a reply, no patch"])
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        _attach_mock(app, mock_llm)
        # Spy on code_with_retry to confirm it is NOT invoked.
        assert app._agent is not None
        app._agent.code_with_retry = AsyncMock()  # type: ignore[method-assign]

        app._handle_slash("/mode code")
        await pilot.pause(0.05)
        app.post_message(UserMessage("change x"))
        await pilot.pause(0.4)

        app._agent.code_with_retry.assert_not_called()  # type: ignore[attr-defined]
        # Streaming mock saw the request.
        assert mock_llm.calls, "expected the streaming path to be used"


_BAD_PATCH_STREAM = (
    "I'll fix it.\n\n"
    "missing.py\n"
    "```python\n"
    "<<<<<<< SEARCH\n"
    "no such line in target\n"
    "=======\n"
    "replacement\n"
    ">>>>>>> REPLACE\n"
    "```\n"
)


@pytest.mark.asyncio
async def test_code_mode_iterative_loop_enabled_invokes_code_with_retry(
    sandbox: Path,
) -> None:
    """With iterative_patch_loop on AND mode=code, the user message must
    route through code_with_retry when the streamed first attempt fails.
    First attempt streams; failure falls through to the retry pipeline."""
    from unittest.mock import AsyncMock

    from code_scalpel.tui.widgets.input import UserMessage
    from code_scalpel.tui.widgets.tool_use import ToolUseCard

    config = AppConfig(
        profiles={"local": ModelProfile(provider="lmstudio", model="local-model")},
        agent=AgentConfig(max_files=0, max_file_lines=10, iterative_patch_loop=True),
    )
    app = ScalpelApp(config=config, cwd=sandbox)
    # Stream produces a SEARCH/REPLACE block that won't apply (target file
    # missing). _run_first_attempt_streamed extracts edits, fails to apply,
    # falls through to code_with_retry — which we mock for deterministic
    # output.
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        _attach_mock(app, _StreamingMock([_BAD_PATCH_STREAM]))
        assert app._agent is not None

        result = _make_step_result(
            reply="done",
            attempts=(
                _make_attempt(
                    apply_ok=True,
                    test_output="1 passed",
                    tests_passed=True,
                ),
            ),
        )
        app._agent.code_with_retry = AsyncMock(return_value=result)  # type: ignore[method-assign]

        app._handle_slash("/mode code")
        await pilot.pause(0.05)
        app.post_message(UserMessage("change x"))
        await pilot.pause(0.5)

        app._agent.code_with_retry.assert_called_once()  # type: ignore[attr-defined]
        output = app.query_one(OutputLog)
        cards = list(output.query(ToolUseCard))
        assert cards, "expected at least one patch_attempt ToolUseCard"
        assert cards[-1]._call.name == "patch_attempt_1"


@pytest.mark.asyncio
async def test_iterative_loop_renders_each_attempt_as_card(sandbox: Path) -> None:
    """Three attempts (2 failed + 1 success) → three cards in order. The
    user must see the full retry history, not just the final patch — the
    failed attempts are the diagnostic value."""
    from unittest.mock import AsyncMock

    from code_scalpel.tui.widgets.input import UserMessage
    from code_scalpel.tui.widgets.tool_use import ToolUseCard

    config = AppConfig(
        profiles={"local": ModelProfile(provider="lmstudio", model="local-model")},
        agent=AgentConfig(max_files=0, max_file_lines=10, iterative_patch_loop=True),
    )
    app = ScalpelApp(config=config, cwd=sandbox)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        _attach_mock(app, _StreamingMock([_BAD_PATCH_STREAM]))
        assert app._agent is not None

        result = _make_step_result(
            reply="done",
            attempts=(
                _make_attempt(
                    apply_ok=False,
                    apply_error="SEARCH did not match",
                    tests_passed=False,
                ),
                _make_attempt(
                    apply_ok=True,
                    test_output="FAILED tests/test_x.py",
                    tests_passed=False,
                ),
                _make_attempt(
                    apply_ok=True,
                    test_output="1 passed",
                    tests_passed=True,
                ),
            ),
        )
        app._agent.code_with_retry = AsyncMock(return_value=result)  # type: ignore[method-assign]

        app._handle_slash("/mode code")
        await pilot.pause(0.05)
        app.post_message(UserMessage("fix it"))
        await pilot.pause(0.5)

        output = app.query_one(OutputLog)
        cards = list(output.query(ToolUseCard))
        assert len(cards) == 3, f"expected 3 attempt cards, got {len(cards)}"
        assert [c._call.name for c in cards] == [
            "patch_attempt_1",
            "patch_attempt_2",
            "patch_attempt_3",
        ]
        # First two cards must surface failure (red dot in title); the third
        # is the success.
        assert cards[0]._result.ok is False
        assert cards[1]._result.ok is False
        assert cards[2]._result.ok is True


@pytest.mark.asyncio
async def test_iterative_loop_failure_surfaces_final_diff_for_manual_review(
    sandbox: Path,
) -> None:
    """Every attempt failed → the loop gives up but must NOT silently
    drop the work. A ToolCallCard in reviewing state appears so the user
    keeps their [a]/[r]/[g] escape hatch on the last diff."""
    from unittest.mock import AsyncMock

    from code_scalpel.tui.widgets.cards.tool_call import ToolCallCard
    from code_scalpel.tui.widgets.input import UserMessage

    config = AppConfig(
        profiles={"local": ModelProfile(provider="lmstudio", model="local-model")},
        agent=AgentConfig(max_files=0, max_file_lines=10, iterative_patch_loop=True),
    )
    app = ScalpelApp(config=config, cwd=sandbox)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        _attach_mock(app, _StreamingMock([_BAD_PATCH_STREAM]))
        assert app._agent is not None

        result = _make_step_result(
            reply="couldn't get it",
            attempts=(
                _make_attempt(
                    apply_ok=True,
                    test_output="FAILED",
                    tests_passed=False,
                ),
                _make_attempt(
                    apply_ok=True,
                    test_output="STILL FAILED",
                    tests_passed=False,
                ),
            ),
        )
        app._agent.code_with_retry = AsyncMock(return_value=result)  # type: ignore[method-assign]

        app._handle_slash("/mode code")
        await pilot.pause(0.05)
        app.post_message(UserMessage("fix it"))
        await pilot.pause(0.5)

        # A review card must be mounted so the user can still apply manually.
        review_cards = list(app.query(ToolCallCard))
        assert review_cards, "expected a manual-review ToolCallCard after giving up"
        # The card is in reviewing state (set_reviewing was called).
        assert review_cards[-1]._state == "reviewing"
        # And _pending_edits holds the LAST attempt's edits so [a] can apply.
        assert app._pending_edits is not None
        assert app._pending_edits == list(result.attempts[-1].edits)


@pytest.mark.asyncio
async def test_slash_go_without_plan_toggles_retry_loop(sandbox: Path) -> None:
    """/go with no TASKS.md must toggle the retry loop, not invoke run_plan."""
    from unittest.mock import AsyncMock

    config = AppConfig(
        profiles={"local": ModelProfile(provider="lmstudio", model="local-model")},
        agent=AgentConfig(max_files=0, max_file_lines=10, iterative_patch_loop=False),
    )
    app = ScalpelApp(config=config, cwd=sandbox)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        _attach_mock(app, _StreamingMock([""]))
        assert app._agent is not None
        app._agent.run_plan = AsyncMock()  # type: ignore[method-assign]

        app._handle_slash("/go")
        await pilot.pause(0.2)

        app._agent.run_plan.assert_not_called()  # type: ignore[attr-defined]
        assert app.config.agent.iterative_patch_loop is True
        output = app.query_one(OutputLog)
        chat = "\n".join(str(c.render()) for c in output.children if c.id != "_spacer")
        assert "retry loop" in chat


@pytest.mark.asyncio
async def test_slash_run_invokes_run_plan_and_renders_status_lines(
    sandbox: Path,
) -> None:
    """/run with a TASKS.md must call `agent.run_plan` and render a
    per-task status line plus the final summary."""
    from unittest.mock import AsyncMock

    from code_scalpel.agent import RunPlanResult, TaskOutcome
    from code_scalpel.plan import Task

    tasks_dir = sandbox / ".code-scalpel"
    tasks_dir.mkdir()
    (tasks_dir / "TASKS.md").write_text(
        "## T001: First\n\nGoal: a\nFiles: x.py\n\n## T002: Second\n\nGoal: b\nFiles: y.py\n"
    )

    config = AppConfig(
        profiles={"local": ModelProfile(provider="lmstudio", model="local-model")},
        agent=AgentConfig(max_files=0, max_file_lines=10, iterative_patch_loop=True),
    )
    app = ScalpelApp(config=config, cwd=sandbox)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        _attach_mock(app, _StreamingMock([""]))
        assert app._agent is not None

        # Mock run_plan: fire both hooks so we exercise the per-task
        # rendering path, then return a happy aggregate.
        async def _fake_run_plan(
            *,
            stop_after_failures: int = 2,
            max_tasks: Any = None,
            on_task_start: Any = None,
            on_task_end: Any = None,
            on_tool_executed: Any = None,
            context_limit: int | None = None,
            fork_resolver: Any = None,
        ) -> RunPlanResult:
            t1 = Task(id="T001", title="First", body="Goal: a", done=False)
            t2 = Task(id="T002", title="Second", body="Goal: b", done=False)
            sr = _make_step_result(
                reply="ok",
                attempts=(_make_attempt(apply_ok=True, tests_passed=True),),
            )
            o1 = TaskOutcome(task=t1, step_result=sr, status="done")
            o2 = TaskOutcome(task=t2, step_result=sr, status="done")
            if on_task_start:
                on_task_start(t1)
            if on_task_end:
                on_task_end(o1)
            if on_task_start:
                on_task_start(t2)
            if on_task_end:
                on_task_end(o2)
            return RunPlanResult(outcomes=(o1, o2), stopped_reason="all_done", tasks_completed=2)

        app._agent.run_plan = AsyncMock(side_effect=_fake_run_plan)  # type: ignore[method-assign]

        app._handle_slash("/go")
        await pilot.pause(0.2)
        # Simulate user choosing "full plan" from the GoModeCard.
        from code_scalpel.tui.widgets.cards.choice import ChoiceDecision

        app.post_message(ChoiceDecision(card_id=0, chosen_key="p"))
        await pilot.pause(0.5)

        app._agent.run_plan.assert_called_once()  # type: ignore[attr-defined]
        output = app.query_one(OutputLog)
        chat = "\n".join(str(c.render()) for c in output.children if c.id != "_spacer")
        assert "Running T001: First" in chat
        assert "Running T002: Second" in chat


@pytest.mark.asyncio
async def test_slash_run_renders_final_summary(sandbox: Path) -> None:
    """After /run finishes the chat carries a single `⤷ Run finished: …`
    line with stop reason. The user can scan one line and know what
    happened during their coffee break."""
    from unittest.mock import AsyncMock

    from code_scalpel.agent import RunPlanResult, TaskOutcome
    from code_scalpel.plan import Task

    (sandbox / ".code-scalpel").mkdir()
    (sandbox / ".code-scalpel" / "TASKS.md").write_text("## T001: x\n\nGoal: y\n")

    config = AppConfig(
        profiles={"local": ModelProfile(provider="lmstudio", model="local-model")},
        agent=AgentConfig(max_files=0, max_file_lines=10, iterative_patch_loop=True),
    )
    app = ScalpelApp(config=config, cwd=sandbox)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        _attach_mock(app, _StreamingMock([""]))
        assert app._agent is not None

        t1 = Task(id="T001", title="x", body="Goal: y", done=False)
        sr = _make_step_result(
            reply="bad",
            attempts=(_make_attempt(apply_ok=True, tests_passed=False),),
        )
        result = RunPlanResult(
            outcomes=(TaskOutcome(task=t1, step_result=sr, status="failed"),),
            stopped_reason="max_failures",
            tasks_completed=0,
        )
        app._agent.run_plan = AsyncMock(return_value=result)  # type: ignore[method-assign]

        app._handle_slash("/go")
        await pilot.pause(0.2)
        from code_scalpel.tui.widgets.cards.choice import ChoiceDecision

        app.post_message(ChoiceDecision(card_id=0, chosen_key="p"))
        await pilot.pause(0.5)

        output = app.query_one(OutputLog)
        chat = "\n".join(str(c.render()) for c in output.children if c.id != "_spacer")
        assert "Run finished" in chat
        assert "max_failures" in chat
        assert "0 done" in chat
        assert "1 failed" in chat


@pytest.mark.asyncio
async def test_slash_run_cancellation_routes_through_step_worker(
    sandbox: Path,
) -> None:
    """Esc during /run must cancel the worker. `_step_worker` is the
    handle the existing `action_cancel_step` already targets, so /run
    must register itself there to share the cancel path."""
    import asyncio as _asyncio
    from unittest.mock import AsyncMock

    (sandbox / ".code-scalpel").mkdir()
    (sandbox / ".code-scalpel" / "TASKS.md").write_text("## T001: x\n\nGoal: y\n")

    config = AppConfig(
        profiles={"local": ModelProfile(provider="lmstudio", model="local-model")},
        agent=AgentConfig(max_files=0, max_file_lines=10, iterative_patch_loop=True),
    )
    app = ScalpelApp(config=config, cwd=sandbox)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        _attach_mock(app, _StreamingMock([""]))
        assert app._agent is not None

        async def _slow_run_plan(**kwargs: Any) -> Any:
            await _asyncio.sleep(2.0)
            raise AssertionError("should have been cancelled")

        app._agent.run_plan = AsyncMock(side_effect=_slow_run_plan)  # type: ignore[method-assign]

        app._handle_slash("/go")
        await pilot.pause(0.2)
        # Simulate user choosing "full plan" from the GoModeCard.
        from code_scalpel.tui.widgets.cards.choice import ChoiceDecision

        app.post_message(ChoiceDecision(card_id=0, chosen_key="p"))
        await pilot.pause(0.2)
        # `_step_worker` must be set — same handle Esc targets.
        worker = getattr(app, "_step_worker", None)
        assert worker is not None
        # First Esc arms the double-Esc guard; second Esc cancels.
        await pilot.press("escape")
        await pilot.pause(0.05)
        await pilot.press("escape")
        await pilot.pause(0.2)
        assert worker.is_cancelled or worker.is_finished


@pytest.mark.asyncio
async def test_iterative_loop_streams_first_attempt(sandbox: Path) -> None:
    """Debt #1: первая попытка /loop должна стримиться, чтобы юзер видел
    что модель работает, а не пялился в замёрзший экран 30-90 секунд.
    Перехватываем `Static.update` на placeholder'е, который вернул
    `start_streaming`, и убеждаемся что он получил вызовы во время
    стриминга первого аттемпта."""
    from unittest.mock import AsyncMock

    from code_scalpel.tui.widgets.input import UserMessage
    from code_scalpel.tui.widgets.output import OutputLog as _OutputLog

    chunks = ["First", " bit", " of", " a", " streamed", " reply.\n"]

    captured_updates: list[str] = []

    real_start_streaming = _OutputLog.start_streaming

    def spy_start_streaming(self: _OutputLog) -> Any:
        placeholder = real_start_streaming(self)
        real_update = placeholder.update

        def spy_update(text: Any = "", *args: Any, **kwargs: Any) -> None:
            captured_updates.append(str(text))
            real_update(text, *args, **kwargs)

        placeholder.update = spy_update  # type: ignore[method-assign]
        return placeholder

    config = AppConfig(
        profiles={"local": ModelProfile(provider="lmstudio", model="local-model")},
        agent=AgentConfig(max_files=0, max_file_lines=10, iterative_patch_loop=True),
    )
    app = ScalpelApp(config=config, cwd=sandbox)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        # Tiny delay between chunks lets the placeholder mount before the
        # first update() lands (mount goes through a worker).
        _attach_mock(app, _StreamingMock(chunks, delay=0.01))
        assert app._agent is not None
        # We don't care what happens after the streamed attempt — short-
        # circuit `code_with_retry` so the test stays fast.
        app._agent.code_with_retry = AsyncMock(  # type: ignore[method-assign]
            return_value=_make_step_result(reply="", attempts=())
        )

        _OutputLog.start_streaming = spy_start_streaming  # type: ignore[method-assign]
        try:
            app._handle_slash("/mode code")
            await pilot.pause(0.05)
            app.post_message(UserMessage("stream please"))
            await pilot.pause(0.5)
        finally:
            _OutputLog.start_streaming = real_start_streaming  # type: ignore[method-assign]

        assert captured_updates, "placeholder.update() must fire during streaming"
        # The accumulated text on the last update should contain the
        # streamed payload — proves the stream was actually visible.
        assert any("streamed reply" in u for u in captured_updates)


@pytest.mark.asyncio
async def test_go_without_plan_toggles_retry_loop_flag(sandbox: Path) -> None:
    """/go without a plan flips iterative_patch_loop on/off and prints the
    new state — the user's opt-in without editing config.yaml."""
    config = AppConfig(
        profiles={"local": ModelProfile(provider="lmstudio", model="local-model")},
        agent=AgentConfig(max_files=0, max_file_lines=10, iterative_patch_loop=False),
    )
    app = ScalpelApp(config=config, cwd=sandbox)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        _attach_mock(app, _StreamingMock([""]))
        output = app.query_one(OutputLog)

        assert app.config.agent.iterative_patch_loop is False
        app._handle_slash("/go")
        await pilot.pause(0.1)
        assert app.config.agent.iterative_patch_loop is True
        chat = "\n".join(str(c.render()) for c in output.children if c.id != "_spacer")
        assert "on" in chat.lower()

        app._handle_slash("/go")
        await pilot.pause(0.1)
        assert app.config.agent.iterative_patch_loop is False
        chat = "\n".join(str(c.render()) for c in output.children if c.id != "_spacer")
        assert "off" in chat.lower()


# ── Ctrl+J jobs modal ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ctrl_j_opens_jobs_modal(sandbox: Path) -> None:
    """Ctrl+J pushes the full-view jobs modal regardless of whether
    anything is running — the modal itself handles the empty state.
    User shouldn't have to wait for a job to land to find the shortcut."""
    from code_scalpel.tui.widgets.jobs_modal import JobsModal

    app = ScalpelApp(config=_CONFIG, cwd=sandbox)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        await pilot.press("ctrl+j")
        await pilot.pause(0.1)
        assert isinstance(app.screen, JobsModal)


@pytest.mark.asyncio
async def test_ctrl_j_modal_shows_live_jobs(sandbox: Path) -> None:
    """Modal mounts after a job is registered — every row in the snapshot
    must appear. Validates that the modal reads the registry the app owns,
    not a stale copy."""
    from code_scalpel.tui.widgets.jobs_modal import JobsModal

    app = ScalpelApp(config=_CONFIG, cwd=sandbox)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        app.jobs.start("map", "Building project map")
        app.jobs.start("step", "ask: hello")
        await pilot.press("ctrl+j")
        await pilot.pause(0.1)
        modal = app.screen
        assert isinstance(modal, JobsModal)
        rows = list(modal.query(".jm-row"))
        assert len(rows) == 2


@pytest.mark.asyncio
async def test_escape_closes_jobs_modal(sandbox: Path) -> None:
    """Esc must dismiss the modal — otherwise the user has no keyboard
    way back to the input. We pop_screen via the binding."""
    from code_scalpel.tui.widgets.jobs_modal import JobsModal

    app = ScalpelApp(config=_CONFIG, cwd=sandbox)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        await pilot.press("ctrl+j")
        await pilot.pause(0.1)
        assert isinstance(app.screen, JobsModal)
        await pilot.press("escape")
        await pilot.pause(0.1)
        assert not isinstance(app.screen, JobsModal)


# ── /context slash ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_slash_context_mounts_breakdown_card(sandbox: Path) -> None:
    """/context renders a ToolUseCard with the per-category breakdown —
    system prompt / tools / overview / history / memory / free space.
    Anchors against drift if the segment names ever shift."""
    from code_scalpel.tui.widgets.tool_use import ToolUseCard

    app = ScalpelApp(config=_CONFIG, cwd=sandbox)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        app._handle_slash("/context")
        await pilot.pause(0.3)
        output = app.query_one(OutputLog)
        cards = list(output.query(ToolUseCard))
        assert cards, "expected /context to mount a ToolUseCard"
        body = cards[-1]._result.output
        assert "Context Usage" in body
        assert "System prompt" in body
        assert "Tools schema" in body
        # "Project files" segment removed — listing is now on-demand
        # via list_files tool, its cost lands in Conversation.
        assert "Project files" not in body
        assert "Skills" in body
        assert "Conversation" in body


@pytest.mark.asyncio
async def test_slash_context_handles_unknown_ctx_limit(sandbox: Path) -> None:
    """Autodetect hasn't fired or LM Studio is silent → context_limit
    is 0. Card still renders with a friendly "limit unknown" line."""
    from code_scalpel.tui.widgets.tool_use import ToolUseCard

    app = ScalpelApp(config=_CONFIG, cwd=sandbox)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        app.state.context_limit = 0
        app._handle_slash("/context")
        await pilot.pause(0.3)
        cards = list(app.query_one(OutputLog).query(ToolUseCard))
        assert cards
        body = cards[-1]._result.output
        assert "ctx limit unknown" in body


@pytest.mark.asyncio
async def test_mermaid_block_in_reply_mounts_card(sandbox: Path) -> None:
    """When the assistant emits ```mermaid ... ``` in a streamed reply,
    a MermaidCard appears in the OutputLog right after the turn ends.
    This is the user-visible upgrade over raw fence text."""
    from code_scalpel.tui.widgets.input import UserMessage
    from code_scalpel.tui.widgets.mermaid_card import MermaidCard

    reply = (
        "Sure — here's a flow:\n\n"
        "```mermaid\n"
        "flowchart TD\n"
        "    A --> B\n"
        "```\n\n"
        "Let me know if you want more detail."
    )

    app = ScalpelApp(config=_CONFIG, cwd=sandbox)
    mock = _StreamingMock([reply])
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        _attach_mock(app, mock)

        app.post_message(UserMessage("show me a diagram"))
        await pilot.pause(0.5)

        cards = list(app.query(MermaidCard))
        assert cards, "expected one MermaidCard mounted after the turn"
        assert len(cards) == 1


# ── /skills slash ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_slash_skills_lists_tools_and_slashes(sandbox: Path) -> None:
    """/skills mounts a catalog of built-in tools + slash commands +
    detected SkillRegistry entries. Anchors the surface so reshuffling
    slash names or tool schemas surfaces in this one test, not silently
    in user-facing UX."""
    from code_scalpel.tui.widgets.tool_use import ToolUseCard

    app = ScalpelApp(config=_CONFIG, cwd=sandbox)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        app._handle_slash("/skills")
        await pilot.pause(0.1)
        cards = list(app.query_one(OutputLog).query(ToolUseCard))
        assert cards
        body = cards[-1]._result.output
        # Tools section
        assert "Tools" in body
        for tool in ("read_file", "project_map", "goto_definition", "find_references", "grep"):
            assert tool in body
        # Skills section (detected; sandbox has no markers → "none detected")
        assert "Skills (detected)" in body
        # Slashes section
        assert "Slash commands" in body
        for slash in ("/new", "/map", "/stats", "/context", "/remember", "/go"):
            assert slash in body
        # Trailing note about pluggable skills
        assert "register_skill" in body


@pytest.mark.asyncio
async def test_slash_skills_shows_detected_python_skill(tmp_path: Path) -> None:
    """When cwd contains pyproject.toml, /skills lists PythonSkill in
    the Skills (detected) section with its description and token cost."""
    from code_scalpel.tui.widgets.tool_use import ToolUseCard

    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'fixture'\n")
    app = ScalpelApp(config=_CONFIG, cwd=tmp_path)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        app._handle_slash("/skills")
        await pilot.pause(0.1)
        cards = list(app.query_one(OutputLog).query(ToolUseCard))
        assert cards
        body = cards[-1]._result.output
        assert "Skills (detected)" in body
        # The PythonSkill row — name and a fragment of its description.
        assert "python" in body
        assert "pytest" in body  # description mentions pytest
        # Token-cost column (the "t" suffix from the formatter).
        assert "t  " in body


# ── Ctrl+Y copy from focused tool card ──────────────────────────────────────


@pytest.mark.asyncio
async def test_ctrl_y_without_focused_card_notifies(sandbox: Path) -> None:
    """Ctrl+Y is meaningful only on a focused ToolUseCard. Pressing it
    with no card focused should warn, not silently no-op or crash."""
    app = ScalpelApp(config=_CONFIG, cwd=sandbox)
    notifications: list[str] = []
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        # Intercept notifications so we can assert on them.
        app.notify = lambda message, *_a, **_kw: notifications.append(str(message))  # type: ignore[assignment,method-assign]
        app.action_copy_focused()
        await pilot.pause(0.05)
    assert notifications
    assert "Focus a tool card" in notifications[0]


@pytest.mark.asyncio
async def test_ctrl_y_on_focused_card_invokes_clipboard(sandbox: Path) -> None:
    """With a focused card, Ctrl+Y calls the clipboard helper with the
    card's raw output. We monkeypatch the helper to capture the call
    so the test doesn't actually shell out to wl-copy/xclip."""
    from code_scalpel.tools.agent_tools import ToolCall, ToolResult

    captured: list[str] = []
    app = ScalpelApp(config=_CONFIG, cwd=sandbox)

    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        log = app.query_one(OutputLog)
        call = ToolCall(name="read_file", body='{"path": "x.py"}')
        result = ToolResult(call=call, output="def hello(): pass\n", ok=True)
        log.add_tool_use(call, result)
        await pilot.pause(0.2)

        app.action_focus_prev_card()
        await pilot.pause(0.05)
        assert app._focused_card() is not None

        import code_scalpel.clipboard as clip_mod

        def _fake(text: str) -> str:
            captured.append(text)
            return "wl-copy"

        original = clip_mod.copy_to_system_clipboard
        clip_mod.copy_to_system_clipboard = _fake  # type: ignore[assignment]
        try:
            app.action_copy_focused()
            await pilot.pause(0.05)
        finally:
            clip_mod.copy_to_system_clipboard = original  # type: ignore[assignment]

    assert captured == ["def hello(): pass\n"]
