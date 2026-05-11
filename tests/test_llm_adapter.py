from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from code_scalpel.llm.adapter import ChatResponse, LLMAdapter, OpenAICompatibleAdapter
from tests.mocks import MockLLMAdapter


def test_mock_satisfies_protocol() -> None:
    mock = MockLLMAdapter()
    assert isinstance(mock, LLMAdapter)


@pytest.mark.asyncio
async def test_mock_chat_basic() -> None:
    mock = MockLLMAdapter(["Hello world"])
    resp = await mock.chat([{"role": "user", "content": "hi"}])
    assert isinstance(resp, ChatResponse)
    assert resp.content == "Hello world"
    assert len(mock.calls) == 1


@pytest.mark.asyncio
async def test_mock_stream_yields_chars() -> None:
    mock = MockLLMAdapter(["abc"])
    chunks = []
    async for chunk in mock.stream([{"role": "user", "content": "hi"}]):
        # The final usage chunk has empty text; skip so we're just
        # inspecting the model's character-level stream.
        if chunk.text:
            chunks.append(chunk.text)
    assert chunks == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_mock_multiple_responses_cycle() -> None:
    mock = MockLLMAdapter(["first", "second"])
    r1 = await mock.chat([{"role": "user", "content": "1"}])
    r2 = await mock.chat([{"role": "user", "content": "2"}])
    r3 = await mock.chat([{"role": "user", "content": "3"}])
    assert r1.content == "first"
    assert r2.content == "second"
    assert r3.content == "second"  # clamps at last


def test_chat_response_frozen() -> None:
    resp = ChatResponse(content="x", prompt_tokens=1, completion_tokens=2, cost=None)
    with pytest.raises(AttributeError):
        resp.content = "y"  # type: ignore[misc]


@pytest.mark.asyncio
async def test_openai_adapter_chat() -> None:
    mock_usage = MagicMock()
    mock_usage.prompt_tokens = 10
    mock_usage.completion_tokens = 5
    mock_usage.cost = None

    mock_message = MagicMock()
    mock_message.content = "Test response"

    mock_choice = MagicMock()
    mock_choice.message = mock_message

    mock_completion = MagicMock()
    mock_completion.choices = [mock_choice]
    mock_completion.usage = mock_usage

    with patch("code_scalpel.llm.adapter.AsyncOpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_completion)
        mock_cls.return_value = mock_client

        adapter = OpenAICompatibleAdapter(
            base_url="http://localhost:1234/v1",
            api_key="lm-studio",
            model="qwen2.5-coder-14b-instruct",
        )
        resp = await adapter.chat([{"role": "user", "content": "hello"}])

    assert resp.content == "Test response"
    assert resp.prompt_tokens == 10
    assert resp.completion_tokens == 5
    assert resp.cost is None


@pytest.mark.asyncio
async def test_openai_adapter_stream() -> None:
    def make_chunk(content: str | None) -> MagicMock:
        chunk = MagicMock()
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta.content = content
        return chunk

    raw_chunks = [make_chunk("He"), make_chunk("llo"), make_chunk(None)]

    async def fake_aiter(*args: object, **kwargs: object) -> object:
        return _AsyncIter(raw_chunks)

    class _AsyncIter:
        def __init__(self, items: list[MagicMock]) -> None:
            self._items = iter(items)

        def __aiter__(self) -> _AsyncIter:
            return self

        async def __anext__(self) -> MagicMock:
            try:
                return next(self._items)
            except StopIteration as exc:
                raise StopAsyncIteration from exc

    with patch("code_scalpel.llm.adapter.AsyncOpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=_AsyncIter(raw_chunks))
        mock_cls.return_value = mock_client

        adapter = OpenAICompatibleAdapter(
            base_url="http://localhost:1234/v1",
            api_key="lm-studio",
            model="qwen2.5-coder-14b-instruct",
        )
        result = []
        async for chunk in adapter.stream([{"role": "user", "content": "hi"}]):
            if chunk.text:
                result.append(chunk.text)

    assert result == ["He", "llo"]


@pytest.mark.asyncio
async def test_stream_accumulates_tool_call_across_chunks() -> None:
    """OpenAI streaming delivers tool_call fields incrementally: id+name
    arrive in one chunk, arguments are split across N subsequent chunks.
    The adapter must accumulate `function.arguments` into one
    NativeToolCall yielded at end-of-stream. Otherwise tool-using turns
    fail mid-flight."""

    def make_chunk(
        text: str | None = None,
        tc_index: int | None = None,
        tc_id: str | None = None,
        tc_name: str | None = None,
        tc_args: str | None = None,
    ) -> MagicMock:
        chunk = MagicMock()
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta.content = text
        if tc_index is None:
            chunk.choices[0].delta.tool_calls = None
        else:
            tc = MagicMock()
            tc.index = tc_index
            tc.id = tc_id
            tc.function = MagicMock()
            tc.function.name = tc_name
            tc.function.arguments = tc_args
            chunk.choices[0].delta.tool_calls = [tc]
        return chunk

    class _AsyncIter:
        def __init__(self, items: list[MagicMock]) -> None:
            self._items = iter(items)

        def __aiter__(self) -> _AsyncIter:
            return self

        async def __anext__(self) -> MagicMock:
            try:
                return next(self._items)
            except StopIteration as exc:
                raise StopAsyncIteration from exc

    # Sequence: id+name once, then arguments in three pieces, then a final
    # text chunk (model decided to comment after the call).
    raw = [
        make_chunk(tc_index=0, tc_id="call_42", tc_name="read_file"),
        make_chunk(tc_index=0, tc_args='{"pa'),
        make_chunk(tc_index=0, tc_args='th":'),
        make_chunk(tc_index=0, tc_args=' "x.py"}'),
        make_chunk(text="ok"),
    ]
    with patch("code_scalpel.llm.adapter.AsyncOpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=_AsyncIter(raw))
        mock_cls.return_value = mock_client

        adapter = OpenAICompatibleAdapter(
            base_url="http://localhost:1234/v1",
            api_key="lm-studio",
            model="qwen2.5-coder-14b-instruct",
        )
        text_parts: list[str] = []
        tool_calls = []
        async for chunk in adapter.stream([{"role": "user", "content": "hi"}]):
            if chunk.text:
                text_parts.append(chunk.text)
            if chunk.tool_call is not None:
                tool_calls.append(chunk.tool_call)

    assert text_parts == ["ok"]
    assert len(tool_calls) == 1
    tc = tool_calls[0]
    assert tc.id == "call_42"
    assert tc.name == "read_file"
    # Args were assembled correctly across three delta chunks
    assert tc.arguments == '{"path": "x.py"}'


@pytest.mark.asyncio
async def test_openai_adapter_cost_per_1k() -> None:
    mock_usage = MagicMock()
    mock_usage.prompt_tokens = 1000
    mock_usage.completion_tokens = 500
    mock_usage.cost = None

    mock_message = MagicMock()
    mock_message.content = "x"
    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_completion = MagicMock()
    mock_completion.choices = [mock_choice]
    mock_completion.usage = mock_usage

    with patch("code_scalpel.llm.adapter.AsyncOpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_completion)
        mock_cls.return_value = mock_client

        adapter = OpenAICompatibleAdapter(
            base_url="http://localhost:1234/v1",
            api_key="lm-studio",
            model="qwen",
            cost_per_1k={"input": 0.1, "output": 0.2},
        )
        resp = await adapter.chat([{"role": "user", "content": "hi"}])

    assert resp.cost == pytest.approx(0.1 * 1 + 0.2 * 0.5)
