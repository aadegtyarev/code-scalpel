"""LLM-обёртка для записи всех round-trips в `chat.jsonl`.

Делегирует все вызовы базовому адаптеру без изменения поведения.
Перехват — только запись: messages, response.content, tool_calls,
usage. Stream обрабатывается тем же приёмом — оборачиваем
async iterator и пишем итоговое сообщение когда стрим завершён.

Не лезет в `set_model` и другие методы Protocol'а — прозрачно
проксирует через `__getattr__` если что не покрыто."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from code_scalpel.llm.adapter import ChatResponse, LLMAdapter, StreamChunk
from scripts.probes_v2.state import append_jsonl, utc_now


class LoggingLLMAdapter:
    """Запись round-trips в chat.jsonl + накопление token-счётчиков
    в памяти (для metrics.json в конце прогона).

    chat.jsonl формат — по строке на событие:
      {ts, role: "request", messages: [...], model, request_id}
      {ts, role: "response", content, tool_calls?, usage, request_id}

    request_id монотонный — позволяет матчить запрос ↔ ответ при
    grep'е.
    """

    def __init__(self, inner: LLMAdapter, chat_log: Path) -> None:
        self._inner = inner
        self._chat_log = chat_log
        self._request_id = 0
        # Накапливаем чтобы потом одним блоком обновить metrics.json
        self.requests = 0
        self.prompt_tokens_total = 0
        self.completion_tokens_total = 0
        self.prompt_tokens_peak = 0

    def _next_request_id(self) -> str:
        self._request_id += 1
        return f"r{self._request_id:04d}"

    def _record_usage(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.requests += 1
        self.prompt_tokens_total += prompt_tokens
        self.completion_tokens_total += completion_tokens
        if prompt_tokens > self.prompt_tokens_peak:
            self.prompt_tokens_peak = prompt_tokens

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        request_id = self._next_request_id()
        append_jsonl(
            self._chat_log,
            {
                "ts": utc_now(),
                "role": "request",
                "request_id": request_id,
                "messages": messages,
                "tools": tools,
            },
        )
        response = await self._inner.chat(messages, tools=tools, **kwargs)
        self._record_usage(response.prompt_tokens, response.completion_tokens)
        append_jsonl(
            self._chat_log,
            {
                "ts": utc_now(),
                "role": "response",
                "request_id": request_id,
                "content": response.content,
                "tool_calls": [
                    {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                    for tc in response.tool_calls
                ],
                "prompt_tokens": response.prompt_tokens,
                "completion_tokens": response.completion_tokens,
                "cost": response.cost,
            },
        )
        return response

    def stream(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        return self._stream_logged(messages, tools, kwargs)

    async def _stream_logged(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        kwargs: dict[str, Any],
    ) -> AsyncIterator[StreamChunk]:
        request_id = self._next_request_id()
        append_jsonl(
            self._chat_log,
            {
                "ts": utc_now(),
                "role": "request",
                "request_id": request_id,
                "messages": messages,
                "tools": tools,
                "stream": True,
            },
        )
        text_chunks: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        prompt_tokens = 0
        completion_tokens = 0
        async for chunk in self._inner.stream(messages, tools=tools, **kwargs):
            if chunk.text:
                text_chunks.append(chunk.text)
            if chunk.tool_call is not None:
                tc = chunk.tool_call
                tool_calls.append({"id": tc.id, "name": tc.name, "arguments": tc.arguments})
            if chunk.usage is not None:
                prompt_tokens = chunk.usage.prompt_tokens
                completion_tokens = chunk.usage.completion_tokens
            yield chunk
        self._record_usage(prompt_tokens, completion_tokens)
        append_jsonl(
            self._chat_log,
            {
                "ts": utc_now(),
                "role": "response",
                "request_id": request_id,
                "content": "".join(text_chunks),
                "tool_calls": tool_calls,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "stream": True,
            },
        )

    def set_model(self, model: str) -> None:
        self._inner.set_model(model)

    def __getattr__(self, name: str) -> Any:
        """Прозрачный fallback на inner — если scalpel завёл новый
        метод в LLMAdapter, не плодим override."""
        return getattr(self._inner, name)


__all__ = ["LoggingLLMAdapter"]
