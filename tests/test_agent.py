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
async def test_ask_includes_few_shot_examples(project: Path) -> None:
    """Few-shot examples are load-bearing for weak models — verify they're sent.
    With tool-use enabled the sequence is system + 2 (user,assistant) pairs +
    real task = 6 messages."""
    llm = MockLLMAdapter(["OK"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    await agent.ask("do something")

    messages = llm.calls[0]
    assert len(messages) == 6
    assert messages[0]["role"] == "system"
    # The two demonstration pairs end with an assistant SEARCH/REPLACE.
    assert "SEARCH" in messages[4]["content"]
    # The last message must be the real task
    assert messages[-1]["role"] == "user"
    assert "do something" in messages[-1]["content"]


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
    """If the model emits a read_file tool call, the agent executes it and
    feeds the result back into the conversation."""
    tool_response = "<TOOL: read_file>\nhello.py\n</TOOL>"
    final_response = "Done."
    llm = MockLLMAdapter([tool_response, final_response])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    result = await agent.ask("look")

    assert result.reply == "Done."
    # Two LLM calls: one with the tool call, one with the result fed back.
    assert len(llm.calls) == 2
    # The second call's last message should be a tool result containing hello.py content
    second_call_last = llm.calls[1][-1]
    assert second_call_last["role"] == "user"
    assert "RESULT" in second_call_last["content"]
    assert "def hello" in second_call_last["content"]


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
    contents = [m["content"] for m in second_call]
    joined = "\n".join(contents)
    assert "first task" in joined
    assert "first reply" in joined


@pytest.mark.asyncio
async def test_clear_history_drops_past_turns(project: Path) -> None:
    llm = MockLLMAdapter(["one", "two"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    await agent.ask("first")
    agent.clear_history()
    await agent.ask("second")

    second_call_contents = "\n".join(m["content"] for m in llm.calls[1])
    assert "first" not in second_call_contents.replace("first task", "")  # nothing remains
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
