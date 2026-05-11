from __future__ import annotations

from pathlib import Path

import pytest

from code_scalpel.agent import StepAgent
from code_scalpel.config import AgentConfig, AppConfig, ModelProfile
from tests.mocks import MockLLMAdapter

_EDIT_BLOCK = """\
Here's the fix:

hello.py
```python
<<<<<<< SEARCH
def hello():
    pass
=======
def hello():
    return "hi"
>>>>>>> REPLACE
```
"""

_CONFIG = AppConfig(
    profiles={
        "local": ModelProfile(
            provider="lmstudio",
            model="local-model",
            temperature=0.1,
        )
    },
    agent=AgentConfig(max_files=2, max_file_lines=50),
)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "hello.py").write_text("def hello():\n    pass\n")
    (tmp_path / "main.py").write_text("from hello import hello\nhello()\n")
    return tmp_path


@pytest.mark.asyncio
async def test_ask_extracts_edits(project: Path) -> None:
    llm = MockLLMAdapter([_EDIT_BLOCK])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    result = await agent.ask("make hello return 'hi'")

    assert len(result.edits) == 1
    assert result.edits[0].path == "hello.py"
    assert 'return "hi"' in result.edits[0].replace
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_ask_no_edits_when_plain_text_reply(project: Path) -> None:
    llm = MockLLMAdapter(["Sure, just add a docstring!"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    result = await agent.ask("explain hello")

    assert result.edits == []
    assert result.reply == "Sure, just add a docstring!"


@pytest.mark.asyncio
async def test_ask_sends_system_prompt(project: Path) -> None:
    llm = MockLLMAdapter(["OK"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    await agent.ask("do something")

    messages = llm.calls[0]
    assert messages[0]["role"] == "system"
    # New prompt teaches SEARCH/REPLACE, not unified diff
    assert "SEARCH" in messages[0]["content"]


@pytest.mark.asyncio
async def test_ask_sends_system_and_task_only(project: Path) -> None:
    """With native function calling, tools are declared via API schema —
    no need for few-shot examples. Initial messages = system + task."""
    llm = MockLLMAdapter(["OK"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    await agent.ask("do something")

    messages = llm.calls[0]
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert "do something" in messages[1]["content"]


@pytest.mark.asyncio
async def test_ask_includes_project_map_not_file_content(project: Path) -> None:
    """v0.2: the user message carries a compact map, not full file bodies."""
    llm = MockLLMAdapter(["OK"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    await agent.ask("do something")

    real_task_msg = llm.calls[0][-1]["content"]
    assert "Project map" in real_task_msg
    assert "hello.py" in real_task_msg  # path appears in map
    # Full file body should NOT be there
    assert "def hello():\n    pass" not in real_task_msg


@pytest.mark.asyncio
async def test_ask_records_response_stats(project: Path) -> None:
    llm = MockLLMAdapter(["OK"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    result = await agent.ask("do something")

    assert result.response.completion_tokens > 0


@pytest.mark.asyncio
async def test_map_lists_files_in_subdirs(tmp_path: Path) -> None:
    """Subdirectory files must appear in the project map — not only top-level."""
    (tmp_path / "top.py").write_text("x = 1\n")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "deep.py").write_text("def f():\n    pass\n")
    (tmp_path / "pkg" / "sub").mkdir()
    (tmp_path / "pkg" / "sub" / "deeper.py").write_text("def g():\n    pass\n")

    llm = MockLLMAdapter(["OK"])
    agent = StepAgent(llm=llm, cwd=tmp_path, config=_CONFIG)

    await agent.ask("do something")

    real_task_msg = llm.calls[0][-1]["content"]
    assert "top.py" in real_task_msg
    assert "pkg/deep.py" in real_task_msg
    assert "pkg/sub/deeper.py" in real_task_msg


@pytest.mark.asyncio
async def test_ask_handles_tool_call_loop(project: Path) -> None:
    """Native function calling: model emits structured tool_calls; agent
    executes and appends a tool-role message with the result."""
    from code_scalpel.llm.adapter import NativeToolCall

    tool_call = NativeToolCall(id="call_1", name="read_file", arguments='{"path": "hello.py"}')
    llm = MockLLMAdapter([("", [tool_call]), "Done."])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    result = await agent.ask("look")

    assert result.reply == "Done."
    assert len(llm.calls) == 2
    # The second call must include a tool-role message with the file content
    second_call = llm.calls[1]
    tool_msgs = [m for m in second_call if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["tool_call_id"] == "call_1"
    assert "def hello" in tool_msgs[0]["content"]


@pytest.mark.asyncio
async def test_stream_ask_yields_chunks(project: Path) -> None:
    from code_scalpel.agent import TextDelta

    llm = MockLLMAdapter(["hello"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    items = [c async for c in agent.stream_ask("greet me")]
    text_items = [c for c in items if isinstance(c, TextDelta)]

    assert "".join(c.text for c in text_items) == "hello"
    assert len(text_items) == 5  # per-character stream


@pytest.mark.asyncio
async def test_stream_ask_builds_same_messages_as_ask(project: Path) -> None:
    """Both code paths should construct identical initial messages for the
    same task — history shouldn't sneak into one but not the other."""
    llm = MockLLMAdapter(["X", "X"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    await agent.ask("first")
    agent.clear_history()  # start fresh so stream_ask sees the same initial state
    async for _ in agent.stream_ask("first"):
        pass

    assert llm.calls[0] == llm.calls[1]


@pytest.mark.asyncio
async def test_history_carries_between_turns(project: Path) -> None:
    """Second ask() sees the first exchange in messages."""
    llm = MockLLMAdapter(["first reply", "second reply"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    await agent.ask("first task")
    await agent.ask("second task")

    second_call = llm.calls[1]
    contents = [str(m.get("content") or "") for m in second_call]
    joined = "\n".join(contents)
    assert "first task" in joined
    assert "first reply" in joined


@pytest.mark.asyncio
async def test_history_stores_bare_task_not_map(project: Path) -> None:
    """History entries must contain just the user's task, not the bloated
    'Project map:\n...\n\nTask: foo' wrapper. Otherwise every subsequent turn
    duplicates the map in history."""
    llm = MockLLMAdapter(["ok1", "ok2"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    await agent.ask("first task")

    # The bare task should be what's stored
    assert agent.history[0]["role"] == "user"
    assert agent.history[0]["content"] == "first task"
    assert "Project map" not in agent.history[0]["content"]
    assert agent.history[1]["role"] == "assistant"


@pytest.mark.asyncio
async def test_history_grows_with_each_turn(project: Path) -> None:
    llm = MockLLMAdapter(["one", "two", "three"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    await agent.ask("a")
    assert len(agent.history) == 2

    await agent.ask("b")
    assert len(agent.history) == 4

    await agent.ask("c")
    assert len(agent.history) == 6


@pytest.mark.asyncio
async def test_ask_default_mode_is_ask_temperature(project: Path) -> None:
    """No explicit mode → defaults to 'ask' temperature (lowest, retrieval)."""
    from code_scalpel.config import ModeTemperatures

    cfg = AppConfig(
        profiles={
            "local": ModelProfile(
                provider="lmstudio",
                model="m",
                temperature=ModeTemperatures(ask=0.1, code=0.7),
            )
        },
        agent=AgentConfig(max_files=2, max_file_lines=50),
    )
    llm = MockLLMAdapter(["plain reply"])
    agent = StepAgent(llm=llm, cwd=project, config=cfg)

    await agent.ask("describe hello")

    assert llm.kwargs_calls[0]["temperature"] == 0.1


@pytest.mark.asyncio
async def test_ask_uses_per_mode_temperature(project: Path) -> None:
    from code_scalpel.config import ModeTemperatures

    cfg = AppConfig(
        profiles={
            "local": ModelProfile(
                provider="lmstudio",
                model="m",
                temperature=ModeTemperatures(ask=0.1, plan=0.4, code=0.7, review=0.15, debug=0.9),
            )
        },
        agent=AgentConfig(max_files=2, max_file_lines=50),
    )
    llm = MockLLMAdapter(["a", "b", "c", "d", "e"])
    agent = StepAgent(llm=llm, cwd=project, config=cfg)

    await agent.ask("question", mode="ask")
    await agent.ask("plan a feature", mode="plan")
    await agent.ask("write code", mode="code")
    await agent.ask("review patch", mode="review")
    await agent.ask("retry", mode="debug")

    assert llm.kwargs_calls[0]["temperature"] == 0.1
    assert llm.kwargs_calls[1]["temperature"] == 0.4
    assert llm.kwargs_calls[2]["temperature"] == 0.7
    assert llm.kwargs_calls[3]["temperature"] == 0.15
    assert llm.kwargs_calls[4]["temperature"] == 0.9


@pytest.mark.asyncio
async def test_stream_ask_uses_per_mode_temperature(project: Path) -> None:
    from code_scalpel.config import ModeTemperatures

    cfg = AppConfig(
        profiles={
            "local": ModelProfile(
                provider="lmstudio",
                model="m",
                temperature=ModeTemperatures(ask=0.1, code=0.6),
            )
        },
        agent=AgentConfig(max_files=2, max_file_lines=50),
    )
    llm = MockLLMAdapter(["hi"])
    agent = StepAgent(llm=llm, cwd=project, config=cfg)

    async for _ in agent.stream_ask("do thing", mode="code"):
        pass

    assert llm.kwargs_calls[0]["temperature"] == 0.6


@pytest.mark.asyncio
async def test_compact_uses_ask_temperature(project: Path) -> None:
    """Compact is summarization — should run at the analytical (ask) temp,
    not whatever mode the user is currently in."""
    from code_scalpel.config import ModeTemperatures

    cfg = AppConfig(
        profiles={
            "local": ModelProfile(
                provider="lmstudio",
                model="m",
                temperature=ModeTemperatures(ask=0.1, code=0.7),
            )
        },
        agent=AgentConfig(max_files=2, max_file_lines=50),
    )
    llm = MockLLMAdapter(["something", "summary bullets"])
    agent = StepAgent(llm=llm, cwd=project, config=cfg)

    await agent.ask("primer", mode="code")  # populate history first
    await agent.compact()

    # Two calls total: the code ask and the compact summarization.
    assert llm.kwargs_calls[0]["temperature"] == 0.7  # code ask
    assert llm.kwargs_calls[1]["temperature"] == 0.1  # compact uses ask


@pytest.mark.asyncio
async def test_ask_passes_top_p(project: Path) -> None:
    """top_p is shared across all modes — must show up on every call."""
    llm = MockLLMAdapter(["ok"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)
    await agent.ask("hi")
    assert llm.kwargs_calls[0]["top_p"] == 0.9


@pytest.mark.asyncio
async def test_history_user_messages_are_in_order(project: Path) -> None:
    llm = MockLLMAdapter(["r1", "r2", "r3"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    await agent.ask("first")
    await agent.ask("second")
    await agent.ask("third")

    user_contents = [m["content"] for m in agent.history if m["role"] == "user"]
    assert user_contents == ["first", "second", "third"]


@pytest.mark.asyncio
async def test_history_visible_to_next_ask_in_correct_role(project: Path) -> None:
    """The previous turn must appear as alternating user/assistant in the next call's
    messages, not as some opaque blob."""
    llm = MockLLMAdapter(["first reply", "second reply"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    await agent.ask("first")
    await agent.ask("second")

    second_call = llm.calls[1]
    roles = [m["role"] for m in second_call]
    # system, then history pair (user, assistant), then current user
    assert roles == ["system", "user", "assistant", "user"]
    assert second_call[1]["content"] == "first"
    assert second_call[2]["content"] == "first reply"


@pytest.mark.asyncio
async def test_history_survives_tool_call_rounds(project: Path) -> None:
    """Tool-call round-trips within a turn must NOT pollute history. Only
    the final user task and final assistant text get stored."""
    from code_scalpel.llm.adapter import NativeToolCall

    tc = NativeToolCall(id="c1", name="read_file", arguments='{"path": "hello.py"}')
    llm = MockLLMAdapter([("", [tc]), "Final answer."])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    await agent.ask("look")

    # History should hold exactly 2 messages: bare task + final reply
    assert len(agent.history) == 2
    assert agent.history[0] == {"role": "user", "content": "look"}
    assert agent.history[1] == {"role": "assistant", "content": "Final answer."}


@pytest.mark.asyncio
async def test_clear_history_removes_everything(project: Path) -> None:
    llm = MockLLMAdapter(["r1", "r2"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    await agent.ask("a")
    await agent.ask("b")
    assert len(agent.history) == 4
    agent.clear_history()
    assert agent.history == []


@pytest.mark.asyncio
async def test_clear_history_drops_past_turns(project: Path) -> None:
    llm = MockLLMAdapter(["one", "two"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    await agent.ask("first")
    agent.clear_history()
    await agent.ask("second")

    # Only look at user/assistant messages — the system prompt is a fixed
    # blob that may legitimately contain words like "first" in its rules.
    non_system = [m for m in llm.calls[1] if m.get("role") != "system"]
    second_call_contents = "\n".join(str(m.get("content") or "") for m in non_system)
    assert "first" not in second_call_contents
    assert "second" in second_call_contents


@pytest.mark.asyncio
async def test_compact_summarizes_and_replaces_history(project: Path) -> None:
    llm = MockLLMAdapter(["reply A", "reply B", "- bullet point summary"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    await agent.ask("first")
    await agent.ask("second")
    assert len(agent.history) == 4  # 2 user + 2 assistant

    summary = await agent.compact()
    assert summary is not None
    assert "bullet point summary" in summary
    # After compact, history has just the summary message
    assert len(agent.history) == 1
    assert "Summary of the earlier session" in agent.history[0]["content"]


@pytest.mark.asyncio
async def test_system_prompt_allows_text_only_response() -> None:
    from code_scalpel.agent import _SYSTEM_PROMPT

    text = _SYSTEM_PROMPT.lower()
    assert "plain text" in text


@pytest.mark.asyncio
async def test_system_prompt_mirrors_user_language() -> None:
    from code_scalpel.agent import _SYSTEM_PROMPT

    text = _SYSTEM_PROMPT.lower()
    assert "language" in text and ("same" in text or "user" in text)


@pytest.mark.asyncio
async def test_system_prompt_pins_identity() -> None:
    from code_scalpel.agent import _SYSTEM_PROMPT

    text = _SYSTEM_PROMPT.lower()
    assert "code-scalpel" in text
    assert "anthropic" in text and "openai" in text


@pytest.mark.asyncio
async def test_system_prompt_demands_informal_tone() -> None:
    """The user finds the default formal register grating. Prompt must
    explicitly require 'ты' in Russian and discourage corporate hedging."""
    from code_scalpel.agent import _SYSTEM_PROMPT

    text = _SYSTEM_PROMPT
    # Russian ты/вы guidance is explicit
    assert '"ты"' in text
    assert '"вы"' in text
    # Forbidden formal phrases should be called out as anti-examples
    assert "Извините" in text
    # Tone keyword anchors the section
    assert "tone" in text.lower()


@pytest.mark.asyncio
async def test_system_prompt_carries_grounding_rules() -> None:
    """Grounding rules are the anti-hallucination clause. They MUST stay in
    the prompt — without them the model invents method names from thin air
    (see the summary_line() regression caught on 2026-05-11)."""
    from code_scalpel.agent import _SYSTEM_PROMPT

    text = _SYSTEM_PROMPT.lower()
    assert "grounding" in text
    # Naming must be cross-checked against the MAP
    assert "verify" in text or "does not exist" in text
    # Anti-confabulation rule: similar names don't justify invention
    assert "mark_compacted" in text and "compact" in text
    # Tool descriptions are normative — prompt must direct the model to read
    # them rather than restating the same rules in a competing voice.
    assert "tool" in text and ("description" in text or "normative" in text)
    # Pattern recognition is explicitly rejected as a source of truth.
    assert "pattern recognition" in text or "you might" in text
    # And the dataclass anti-example is in (covers the screenshot bug shape).
    assert "dataclass" in text


# ── plan mode ───────────────────────────────────────────────────────────────


_PLAN_REPLY = """\
Sure, here's the breakdown.

## T001: Add note model

Goal: Define a Note dataclass with title and body fields.
Files: src/notes.py
Acceptance:
- Note has `title: str` and `body: str` fields
- `__eq__` works by content
Test command: pytest tests/test_notes.py::test_note_model

## T002: Add search function

Goal: Add search_notes(query) that filters notes by title or body.
Files: src/notes.py, tests/test_notes.py
Acceptance:
- Case-insensitive substring match
- Empty query returns all notes
Test command: pytest tests/test_notes.py::test_search
"""


@pytest.mark.asyncio
async def test_plan_mode_addendum_in_system_prompt() -> None:
    """Plan mode appends a planning addendum that asks for TASKS.md output."""
    from code_scalpel.agent import StepAgent

    cfg = AppConfig(
        profiles={"local": ModelProfile(provider="lmstudio", model="m")},
        agent=AgentConfig(max_files=2, max_file_lines=50),
    )
    llm = MockLLMAdapter(["ok"])
    agent = StepAgent(llm=llm, cwd=Path("."), config=cfg)
    await agent.ask("plan something", mode="plan")
    system = llm.calls[0][0]["content"]
    assert "PLAN mode" in system
    assert "## T001:" in system
    assert "Acceptance:" in system
    # SEARCH/REPLACE explicitly forbidden in plan mode
    assert "NO SEARCH/REPLACE" in system


@pytest.mark.asyncio
async def test_ask_mode_does_not_inject_plan_addendum(project: Path) -> None:
    """The plan-mode addendum must NOT leak into ask/code/review prompts."""
    llm = MockLLMAdapter(["ok"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)
    await agent.ask("question", mode="ask")
    system = llm.calls[0][0]["content"]
    assert "PLAN mode" not in system


@pytest.mark.asyncio
async def test_plan_mode_saves_tasks_md(project: Path) -> None:
    """A reply that contains a `## T001:` plan gets persisted to
    .code-scalpel/TASKS.md — that's the artifact the user (or run mode)
    will execute next."""
    llm = MockLLMAdapter([_PLAN_REPLY])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)
    await agent.ask("plan note search", mode="plan")
    tasks_md = project / ".code-scalpel" / "TASKS.md"
    assert tasks_md.is_file(), "expected TASKS.md to be written"
    text = tasks_md.read_text()
    assert text.startswith("## T001:")
    assert "## T002:" in text
    # Lead-in chatter is stripped
    assert "Sure, here's" not in text


@pytest.mark.asyncio
async def test_plan_mode_skips_save_when_no_tasks_found(project: Path) -> None:
    """If the model asked a clarifying question instead of producing a
    plan, we shouldn't write a junk TASKS.md."""
    llm = MockLLMAdapter(["What kind of search? Title only, or also body?"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)
    await agent.ask("plan", mode="plan")
    assert not (project / ".code-scalpel" / "TASKS.md").exists()


@pytest.mark.asyncio
async def test_ask_mode_does_not_write_tasks_md(project: Path) -> None:
    """Even if an ask-mode reply happens to contain `## T001:` text,
    don't auto-persist — that's plan mode's job."""
    llm = MockLLMAdapter([_PLAN_REPLY])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)
    await agent.ask("question", mode="ask")
    assert not (project / ".code-scalpel" / "TASKS.md").exists()


@pytest.mark.asyncio
async def test_map_only_prepended_on_first_turn(project: Path) -> None:
    """Map is HUGE (300+ lines for a typical project). Re-prepending it
    on every turn drowns short follow-ups — model defaults to repeating
    its previous answer because the new task is lost in noise. Repro for
    the 2026-05-11 'Sonet' bug: turn 1 asks "как добавить антропик
    моделей", turn 2 says "Sonet" → model just re-output the turn 1 list
    instead of using the clarification.

    Fix: map ONLY on turn 1 (history empty). Subsequent turns send the
    bare task; model has the map in its turn 1 prompt within history
    and can read_file/grep for anything new."""
    llm = MockLLMAdapter(["first reply", "second reply"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    await agent.ask("first question")
    await agent.ask("Sonet")

    # Turn 1 user msg: contains map prefix
    turn1_user = llm.calls[0][-1]["content"]
    assert "Project map" in turn1_user
    assert "first question" in turn1_user

    # Turn 2 user msg: just the bare task, NO map
    turn2_user = llm.calls[1][-1]["content"]
    assert turn2_user == "Sonet"
    assert "Project map" not in turn2_user


@pytest.mark.asyncio
async def test_map_returns_after_clear_history(project: Path) -> None:
    """After /new (clear_history), the next turn is "turn 1" again —
    map should be prepended."""
    llm = MockLLMAdapter(["a", "b", "c"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)
    await agent.ask("first")
    await agent.ask("second")  # no map (history non-empty)
    agent.clear_history()
    await agent.ask("third")  # map should come back
    third_user = llm.calls[2][-1]["content"]
    assert "Project map" in third_user


@pytest.mark.asyncio
async def test_stream_ask_in_plan_mode_also_saves(project: Path) -> None:
    """TUI uses stream_ask, not ask. The plan-saving hook must fire from
    the streaming path too."""
    llm = MockLLMAdapter([_PLAN_REPLY])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)
    async for _ in agent.stream_ask("plan", mode="plan"):
        pass
    assert (project / ".code-scalpel" / "TASKS.md").is_file()


# ── loop guard (force-answer when the model spins on identical tool calls) ──


@pytest.mark.asyncio
async def test_loop_guard_breaks_repeating_tool_calls(project: Path) -> None:
    """If the model emits the SAME tool call twice in a row, the agent
    injects a force-answer message instead of executing again. Otherwise
    a buggy model could loop forever (or until _MAX_TOOL_ROUNDS). The
    guard fires on the second occurrence and the third turn produces
    the final text answer."""
    from code_scalpel.llm.adapter import NativeToolCall

    repeated = NativeToolCall(id="c1", name="read_file", arguments='{"path": "hello.py"}')
    # Round 1: tool_call. Round 2: same tool_call → triggers guard.
    # Round 3: plain text answer.
    llm = MockLLMAdapter(
        [
            ("", [repeated]),
            ("", [repeated]),
            "Final answer based on what I had.",
        ]
    )
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)
    result = await agent.ask("look")
    assert result.reply == "Final answer based on what I had."
    # Three chat() calls — last one received the force-answer prompt.
    assert len(llm.calls) == 3
    third_call = llm.calls[2]
    contents = "\n".join(str(m.get("content") or "") for m in third_call)
    assert "Stop calling" in contents or "answer the original question" in contents


@pytest.mark.asyncio
async def test_loop_guard_works_in_stream_path(project: Path) -> None:
    """Same guard, exercised through stream_ask — TUI's actual path."""
    from code_scalpel.llm.adapter import NativeToolCall

    repeated = NativeToolCall(id="c1", name="read_file", arguments='{"path": "hello.py"}')
    llm = MockLLMAdapter(
        [
            ("", [repeated]),
            ("", [repeated]),
            "Done.",
        ]
    )
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)
    chunks: list[str] = []
    async for item in agent.stream_ask("look"):
        from code_scalpel.agent import TextDelta

        if isinstance(item, TextDelta):
            chunks.append(item.text)
    assert "".join(chunks).endswith("Done.")
    # Force-answer reached the third call
    assert len(llm.calls) == 3
