from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from code_scalpel.llm.adapter import ChatResponse, NativeToolCall, StreamChunk
from code_scalpel.tools.shell import ShellResult

# A response slot can be either a plain text string or a structured pair of
# (text, [tool_calls]) for native function-calling tests.
MockResponse = str | tuple[str, list[NativeToolCall]]


class MockLLMAdapter:
    """Deterministic LLM for tests. Cycles through provided responses."""

    def __init__(self, responses: list[MockResponse] | None = None) -> None:
        self._responses: list[MockResponse] = list(responses or ["OK"])
        self._index = 0
        self.calls: list[list[dict[str, Any]]] = []
        self.kwargs_calls: list[dict[str, Any]] = []

    def _next(self) -> tuple[str, list[NativeToolCall]]:
        resp = self._responses[min(self._index, len(self._responses) - 1)]
        self._index += 1
        if isinstance(resp, tuple):
            return resp
        return resp, []

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,  # noqa: ARG002 — accepted for interface parity
        **kwargs: Any,
    ) -> ChatResponse:
        self.calls.append([dict(m) for m in messages])
        self.kwargs_calls.append(dict(kwargs))
        content, tcs = self._next()
        return ChatResponse(
            content=content,
            prompt_tokens=len(str(messages)),
            completion_tokens=len(content),
            cost=None,
            tool_calls=tuple(tcs),
        )

    async def stream(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,  # noqa: ARG002
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        self.calls.append([dict(m) for m in messages])
        self.kwargs_calls.append(dict(kwargs))
        content, tcs = self._next()
        for char in content:
            yield StreamChunk(text=char)
        for tc in tcs:
            yield StreamChunk(tool_call=tc)

    def set_model(self, model: str) -> None:
        self.model = model


class MockShellRunner:
    """Deterministic shell runner for tests."""

    def __init__(self, responses: list[ShellResult] | None = None) -> None:
        self._responses = list(responses or [ShellResult("", 0)])
        self._index = 0
        self.calls: list[list[str]] = []

    async def run(self, cmd: list[str], cwd: str | None = None, timeout: int = 30) -> ShellResult:
        self.calls.append(cmd)
        resp = self._responses[min(self._index, len(self._responses) - 1)]
        self._index += 1
        return resp
