from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from code_scalpel.llm.adapter import ChatResponse
from code_scalpel.shell import ShellResult


class MockLLMAdapter:
    """Deterministic LLM for tests. Cycles through provided responses."""

    def __init__(self, responses: list[str] | None = None) -> None:
        self._responses = list(responses or ["OK"])
        self._index = 0
        self.calls: list[list[dict[str, str]]] = []

    def _next(self) -> str:
        resp = self._responses[min(self._index, len(self._responses) - 1)]
        self._index += 1
        return resp

    async def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> ChatResponse:
        self.calls.append(messages)
        content = self._next()
        return ChatResponse(
            content=content,
            prompt_tokens=len(str(messages)),
            completion_tokens=len(content),
            cost=None,
        )

    async def stream(self, messages: list[dict[str, str]], **kwargs: Any) -> AsyncIterator[str]:
        self.calls.append(messages)
        content = self._next()
        for char in content:
            yield char


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
