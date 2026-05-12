"""Runtime — the headless entry-point shared by TUI / probe / spy / bench.

The class is small: own a session + memory + agent, expose `stream` /
`ask` / `code_with_retry` that always go through `Session.prepare_turn`.
Tests pin that contract so a future refactor can't accidentally bypass
the language directive on one path and not another.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from code_scalpel.config import AgentConfig, AppConfig, ModelProfile
from code_scalpel.runtime import Runtime
from tests.mocks import MockLLMAdapter

_CONFIG = AppConfig(
    profiles={
        "local": ModelProfile(provider="lmstudio", model="local-model", temperature=0.1),
    },
    agent=AgentConfig(max_files=2, max_file_lines=50, enforce_read_before_show=False),
)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "hello.py").write_text("def hello():\n    pass\n")
    return tmp_path


@pytest.mark.asyncio
async def test_ask_applies_prepare_turn(project: Path) -> None:
    """Runtime.ask must send the agent the prepared text (with the
    language directive), not the raw user input. Otherwise probe/bench
    would hit a different channel than the TUI — the regression that
    caused the `flow` scenario to misbehave for half a day."""
    llm = MockLLMAdapter(["OK"])
    runtime = Runtime(cwd=project, config=_CONFIG, llm=llm, with_memory=False)

    await runtime.ask("привет, опиши проект")
    sent = llm.calls[0]
    user_msg = next(m for m in sent if m["role"] == "user")["content"]
    assert "(Reply in Russian.)" in user_msg
    assert "привет, опиши проект" in user_msg


@pytest.mark.asyncio
async def test_stream_applies_prepare_turn(project: Path) -> None:
    """Same contract for the streaming entry point — probably the path
    the TUI actually uses on every turn."""
    llm = MockLLMAdapter(["OK"])
    runtime = Runtime(cwd=project, config=_CONFIG, llm=llm, with_memory=False)

    async for _ in runtime.stream("hello, show me the project"):
        pass
    sent = llm.calls[0]
    user_msg = next(m for m in sent if m["role"] == "user")["content"]
    assert "(Reply in English.)" in user_msg


@pytest.mark.asyncio
async def test_session_language_persists_across_turns(project: Path) -> None:
    """First turn pins the language; later turns reuse it. Mismatched
    suffixes (en→ru→en) would tell the model the human flipped midway
    and bias replies."""
    llm = MockLLMAdapter(["one", "two", "three"])
    runtime = Runtime(cwd=project, config=_CONFIG, llm=llm, with_memory=False)

    await runtime.ask("первый ход на русском")
    await runtime.ask("second turn switching to English")
    await runtime.ask("третий")
    for call in llm.calls:
        last_user = [m for m in call if m["role"] == "user"][-1]["content"]
        assert "(Reply in Russian.)" in last_user


@pytest.mark.asyncio
async def test_memory_off_does_not_materialise_db(project: Path) -> None:
    """with_memory=False is the default for probe/spy/bench — they must
    NOT write `.code-scalpel/memory.db` under the project they're
    probing. Otherwise the probe leaves residue in the repo."""
    llm = MockLLMAdapter(["OK"])
    runtime = Runtime(cwd=project, config=_CONFIG, llm=llm, with_memory=False)
    assert runtime.memory is None
    assert not (project / ".code-scalpel" / "memory.db").exists()
    await runtime.ask("anything")
    assert not (project / ".code-scalpel" / "memory.db").exists()
