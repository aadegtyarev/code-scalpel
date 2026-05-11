from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol, cast, runtime_checkable

from openai import AsyncOpenAI, AsyncStream
from openai.types.chat import ChatCompletion, ChatCompletionChunk


@dataclass(frozen=True)
class NativeToolCall:
    """A tool call emitted by the model through the function-calling API."""

    id: str
    name: str
    arguments: str  # JSON-encoded string of args


@dataclass(frozen=True)
class ChatResponse:
    content: str
    prompt_tokens: int
    completion_tokens: int
    cost: float | None
    tool_calls: tuple[NativeToolCall, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class StreamChunk:
    """One event from a streaming chat. Either text delta or a fully-formed
    tool call (yielded once at end of stream when accumulation completes)."""

    text: str = ""
    tool_call: NativeToolCall | None = None


@runtime_checkable
class LLMAdapter(Protocol):
    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ChatResponse: ...

    def stream(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]: ...


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

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        params: dict[str, Any] = dict(kwargs)
        if tools:
            params["tools"] = tools
        response = cast(
            ChatCompletion,
            await self._client.chat.completions.create(
                model=self._model,
                messages=messages,  # type: ignore[arg-type]
                stream=False,
                **params,
            ),
        )
        msg = response.choices[0].message
        tool_calls: list[NativeToolCall] = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                fn = getattr(tc, "function", None)
                if fn is None:
                    continue
                tool_calls.append(
                    NativeToolCall(
                        id=tc.id,
                        name=fn.name,
                        arguments=fn.arguments or "{}",
                    )
                )
        usage = response.usage
        return ChatResponse(
            content=msg.content or "",
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            cost=self._calc_cost(usage),
            tool_calls=tuple(tool_calls),
        )

    async def stream(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        params: dict[str, Any] = dict(kwargs)
        if tools:
            params["tools"] = tools
        response = cast(
            AsyncStream[ChatCompletionChunk],
            await self._client.chat.completions.create(
                model=self._model,
                messages=messages,  # type: ignore[arg-type]
                stream=True,
                **params,
            ),
        )
        # Accumulate per-index tool calls across chunks (id and name come once,
        # arguments come incrementally).
        buf: dict[int, dict[str, str]] = {}
        async for chunk in response:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                yield StreamChunk(text=delta.content)
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    slot = buf.setdefault(idx, {"id": "", "name": "", "args": ""})
                    if tc.id:
                        slot["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            slot["name"] = tc.function.name
                        if tc.function.arguments:
                            slot["args"] += tc.function.arguments
        for idx in sorted(buf.keys()):
            slot = buf[idx]
            if slot["name"]:
                yield StreamChunk(
                    tool_call=NativeToolCall(
                        id=slot["id"],
                        name=slot["name"],
                        arguments=slot["args"] or "{}",
                    )
                )

    def _calc_cost(self, usage: Any) -> float | None:
        if usage is None:
            return None
        if hasattr(usage, "cost") and usage.cost is not None:
            return float(usage.cost)
        if self._cost_per_1k:
            return float(
                usage.prompt_tokens * self._cost_per_1k.get("input", 0.0) / 1000
                + usage.completion_tokens * self._cost_per_1k.get("output", 0.0) / 1000
            )
        return None
