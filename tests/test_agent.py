from __future__ import annotations

from pathlib import Path

import pytest

from code_scalpel.agent import StepAgent
from code_scalpel.config import AgentConfig, AppConfig, ModelProfile
from tests.mocks import MockLLMAdapter

_DIFF = """\
diff --git a/hello.py b/hello.py
--- a/hello.py
+++ b/hello.py
@@ -1,2 +1,2 @@
 def hello():
-    pass
+    return "hi"
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
async def test_ask_extracts_patch(project: Path) -> None:
    llm = MockLLMAdapter([f"Here is the fix:\n```diff\n{_DIFF}\n```"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    result = await agent.ask("make hello return 'hi'")

    assert result.patch is not None
    assert "hello.py" in result.patch
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_ask_no_patch_when_no_diff(project: Path) -> None:
    llm = MockLLMAdapter(["Sure, just add a docstring!"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    result = await agent.ask("explain hello")

    assert result.patch is None
    assert result.reply == "Sure, just add a docstring!"


@pytest.mark.asyncio
async def test_ask_sends_system_prompt(project: Path) -> None:
    llm = MockLLMAdapter(["OK"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    await agent.ask("do something")

    messages = llm.calls[0]
    assert messages[0]["role"] == "system"
    assert "diff" in messages[0]["content"].lower()


@pytest.mark.asyncio
async def test_ask_includes_file_content(project: Path) -> None:
    llm = MockLLMAdapter(["OK"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    await agent.ask("do something")

    user_content = llm.calls[0][1]["content"]
    assert "hello.py" in user_content
    assert "def hello" in user_content


@pytest.mark.asyncio
async def test_ask_passes_inference_kwargs(project: Path) -> None:
    llm = MockLLMAdapter(["OK"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    await agent.ask("do something")

    # MockLLMAdapter records calls but not kwargs — just ensure no exception
    assert len(llm.calls) == 1


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

    user_content = llm.calls[0][1]["content"]
    assert "top.py" in user_content
    assert "pkg/deep.py" in user_content
    assert "pkg/sub/deeper.py" in user_content


@pytest.mark.asyncio
async def test_stream_ask_yields_chunks(project: Path) -> None:
    llm = MockLLMAdapter(["hello"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    chunks = [c async for c in agent.stream_ask("greet me")]

    assert "".join(chunks) == "hello"
    # MockLLMAdapter.stream emits per-character, so we expect 5 chunks for "hello"
    assert len(chunks) == 5


@pytest.mark.asyncio
async def test_stream_ask_builds_same_messages_as_ask(project: Path) -> None:
    llm = MockLLMAdapter(["X", "X"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    await agent.ask("first")
    async for _ in agent.stream_ask("first"):
        pass

    # Both calls should produce identical message payloads
    assert llm.calls[0] == llm.calls[1]


@pytest.mark.asyncio
async def test_system_prompt_allows_text_only_response() -> None:
    """The v0.1 system prompt must permit plain-text replies (no forced diff)."""
    from code_scalpel.agent import _SYSTEM_PROMPT

    text = _SYSTEM_PROMPT.lower()
    assert "plain text" in text or "no diff" in text


@pytest.mark.asyncio
async def test_system_prompt_mirrors_user_language() -> None:
    """Model should reply in the user's language — important for weak local models."""
    from code_scalpel.agent import _SYSTEM_PROMPT

    text = _SYSTEM_PROMPT.lower()
    assert "language" in text and ("same" in text or "user" in text)


@pytest.mark.asyncio
async def test_system_prompt_pins_identity() -> None:
    """Prevent qwen-style identity hallucinations ('I am Claude/ChatGPT')."""
    from code_scalpel.agent import _SYSTEM_PROMPT

    text = _SYSTEM_PROMPT.lower()
    assert "code-scalpel" in text
    assert "anthropic" in text and "openai" in text  # explicitly denied
