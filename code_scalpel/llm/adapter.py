from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol, cast, runtime_checkable

from openai import AsyncOpenAI, AsyncStream
from openai.types.chat import ChatCompletion, ChatCompletionChunk


@dataclass(frozen=True)
class ChatResponse:
    content: str
    prompt_tokens: int
    completion_tokens: int
    cost: float | None


@runtime_checkable
class LLMAdapter(Protocol):
    async def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> ChatResponse: ...

    def stream(self, messages: list[dict[str, str]], **kwargs: Any) -> AsyncIterator[str]: ...


class OpenAICompatibleAdapter:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 120.0,
        cost_per_1k: dict[str, float] | None = None,
    ) -> None:
        self._client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key or "lm-studio",
            timeout=timeout,
        )
        self._model = model
        self._cost_per_1k = cost_per_1k

    async def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> ChatResponse:
        response = cast(
            ChatCompletion,
            await self._client.chat.completions.create(
                model=self._model,
                messages=messages,  # type: ignore[arg-type]
                stream=False,
                **kwargs,
            ),
        )
        usage = response.usage
        return ChatResponse(
            content=response.choices[0].message.content or "",
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            cost=self._calc_cost(usage),
        )

    async def stream(self, messages: list[dict[str, str]], **kwargs: Any) -> AsyncIterator[str]:
        response = cast(
            AsyncStream[ChatCompletionChunk],
            await self._client.chat.completions.create(
                model=self._model,
                messages=messages,  # type: ignore[arg-type]
                stream=True,
                **kwargs,
            ),
        )
        async for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    def _calc_cost(self, usage: Any) -> float | None:
        if usage is None:
            return None
        # OpenRouter возвращает cost напрямую в usage
        if hasattr(usage, "cost") and usage.cost is not None:
            return float(usage.cost)
        if self._cost_per_1k:
            return float(
                usage.prompt_tokens * self._cost_per_1k.get("input", 0.0) / 1000
                + usage.completion_tokens * self._cost_per_1k.get("output", 0.0) / 1000
            )
        return None
