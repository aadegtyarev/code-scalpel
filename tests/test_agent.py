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
    """Few-shot examples are load-bearing for weak models — verify they're sent."""
    llm = MockLLMAdapter(["OK"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    await agent.ask("do something")

    messages = llm.calls[0]
    # system + user(example) + assistant(example) + user(real task)
    assert len(messages) == 4
    assert messages[1]["role"] == "user"
    assert messages[2]["role"] == "assistant"
    assert "SEARCH" in messages[2]["content"]


@pytest.mark.asyncio
async def test_ask_includes_file_content(project: Path) -> None:
    llm = MockLLMAdapter(["OK"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    await agent.ask("do something")

    real_task_msg = llm.calls[0][-1]["content"]
    assert "hello.py" in real_task_msg
    assert "def hello" in real_task_msg


@pytest.mark.asyncio
async def test_ask_records_response_stats(project: Path) -> None:
    llm = MockLLMAdapter(["OK"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    result = await agent.ask("do something")

    assert result.response.completion_tokens > 0


@pytest.mark.asyncio
async def test_context_lists_files_in_subdirs(tmp_path: Path) -> None:
    """Subdirectory files must appear in the file listing — not only top-level."""
    (tmp_path / "top.py").write_text("x")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "deep.py").write_text("y")
    (tmp_path / "pkg" / "sub").mkdir()
    (tmp_path / "pkg" / "sub" / "deeper.py").write_text("z")

    llm = MockLLMAdapter(["OK"])
    agent = StepAgent(llm=llm, cwd=tmp_path, config=_CONFIG)

    await agent.ask("do something")

    real_task_msg = llm.calls[0][-1]["content"]
    assert "top.py" in real_task_msg
    assert "pkg/deep.py" in real_task_msg
    assert "pkg/sub/deeper.py" in real_task_msg


@pytest.mark.asyncio
async def test_stream_ask_yields_chunks(project: Path) -> None:
    llm = MockLLMAdapter(["hello"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    chunks = [c async for c in agent.stream_ask("greet me")]

    assert "".join(chunks) == "hello"
    assert len(chunks) == 5  # per-character stream


@pytest.mark.asyncio
async def test_stream_ask_builds_same_messages_as_ask(project: Path) -> None:
    llm = MockLLMAdapter(["X", "X"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    await agent.ask("first")
    async for _ in agent.stream_ask("first"):
        pass

    assert llm.calls[0] == llm.calls[1]


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
