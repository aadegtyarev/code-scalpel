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

    second_call_contents = "\n".join(str(m.get("content") or "") for m in llm.calls[1])
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
