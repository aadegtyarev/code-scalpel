"""Adapter wrapper around LM Studio's native `/api/v1/chat` endpoint.

The OpenAI-compat endpoint we use for the builder loop emits text
deltas and (optionally) a final usage chunk — nothing else. LM
Studio's native endpoint emits twenty events: model load progress,
prompt processing progress, reasoning, tool calls, message content.
For passes that don't need our custom tools (every NarrowPass —
per_step_review, test_sanity, commit_msg, debug_pass, detect_forks,
fork_local_meta, fork_clarify, fork_reviewer, annotate_plan), we
can switch to native and get a real phase bar instead of «◌
thinking…».

Builder stays on OpenAI-compat because it relies on our custom
TOOL_SCHEMAS — the native endpoint doesn't accept those (only its
own MCP tools, which we considered and parked in the backlog).

This module is pure transport: it owns the SSE parser and yields a
typed union of native events. Higher-level UX (`OperationCard`)
consumes the events and renders phases.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlparse

import httpx

from code_scalpel.llm.native_events import (
    ChatEnd,
    ChatStart,
    MessageDelta,
    MessageEnd,
    MessageStart,
    ModelLoadEnd,
    ModelLoadProgress,
    ModelLoadStart,
    NativeStreamEvent,
    PromptProcessingEnd,
    PromptProcessingProgress,
    PromptProcessingStart,
    StreamError,
)


class NativeChatError(RuntimeError):
    """Raised when the native endpoint reports an `error` event or
    the HTTP response itself is non-2xx. Callers can choose to
    surface the message in-card or bubble up."""


def lmstudio_native_url(openai_compat_base: str) -> str:
    """Derive the native `/api/v1/chat` URL from an OpenAI-compat
    `base_url`. The compat URL ends in `/v1` (LM Studio convention);
    we replace the trailing path with `/api/v1/chat`.

    Examples:
      http://localhost:1234/v1            → http://localhost:1234/api/v1/chat
      http://192.168.1.10:1234            → http://192.168.1.10:1234/api/v1/chat
      https://lms.example.com/v1          → https://lms.example.com/api/v1/chat
    """
    parsed = urlparse(openai_compat_base.rstrip("/"))
    # Drop any path; native lives at the root /api/v1/...
    return f"{parsed.scheme}://{parsed.netloc}/api/v1/chat"


def lmstudio_models_url(openai_compat_base: str) -> str:
    """Derive the native models-list URL. Used by `OperationCard`'s
    fallback path to detect whether a cold load is about to happen
    (so it can mount the loading phase even on OpenAI-compat
    requests)."""
    parsed = urlparse(openai_compat_base.rstrip("/"))
    return f"{parsed.scheme}://{parsed.netloc}/api/v1/models"


async def native_chat(
    *,
    base_url: str,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float = 0.7,
    max_tokens: int | None = None,
    response_format: dict[str, Any] | None = None,
    ttl_seconds: int | None = None,
    timeout: float = 120.0,
    client: httpx.AsyncClient | None = None,
) -> AsyncIterator[NativeStreamEvent]:
    """Stream a single chat through `/api/v1/chat`, yielding typed
    events as they arrive over SSE.

    Parameters mirror what NarrowPass already passes through the
    OpenAI-compat path (temperature / max_tokens / response_format)
    plus `ttl_seconds` which is native-only — tells LM Studio how
    long the model should linger after this request.

    `client` lets callers pool connections across calls; if None
    we open a per-call client (fine for tests, ok for one-shot
    NarrowPass invocations).

    Errors:
      - Non-2xx HTTP → `NativeChatError(status, body)`.
      - `error` event in the stream → yielded once as `StreamError`,
        then the iterator ends; callers can decide whether to raise.
    """
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": True,
        "temperature": temperature,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if response_format is not None:
        payload["response_format"] = response_format
    if ttl_seconds is not None:
        payload["ttl"] = ttl_seconds

    url = lmstudio_native_url(base_url)

    async def _consume(http: httpx.AsyncClient) -> AsyncIterator[NativeStreamEvent]:
        async with http.stream("POST", url, json=payload, timeout=timeout) as response:
            if response.status_code >= 400:
                body = await response.aread()
                raise NativeChatError(
                    f"native chat failed: HTTP {response.status_code} — "
                    f"{body.decode('utf-8', errors='replace')[:500]}"
                )
            async for raw_line in response.aiter_lines():
                event = _parse_sse_event(raw_line)
                if event is None:
                    continue
                yield event

    if client is None:
        async with httpx.AsyncClient() as fresh:
            async for ev in _consume(fresh):
                yield ev
    else:
        async for ev in _consume(client):
            yield ev


def _parse_sse_event(raw_line: str) -> NativeStreamEvent | None:
    """Parse a single SSE line into a typed event, or None if the
    line is empty / a comment / a `[DONE]` sentinel / unrecognized.

    LM Studio emits each event as `data: {json}\n` with `\n` blank
    lines between events. We're lenient — unknown event `type`
    fields drop to None rather than blow up, so a future server
    that adds event types doesn't break old clients.
    """
    line = raw_line.strip()
    if not line or not line.startswith("data:"):
        return None
    body = line[len("data:") :].strip()
    if not body or body == "[DONE]":
        return None
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return _event_from_dict(data)


def _event_from_dict(data: dict[str, Any]) -> NativeStreamEvent | None:
    """Map a parsed JSON object to the right event dataclass. Unknown
    `type` values yield None so we silently skip server-side
    additions instead of crashing."""
    event_type = data.get("type")
    if event_type == "chat.start":
        return ChatStart(model_instance_id=str(data.get("model_instance_id", "")))
    if event_type == "model_load.start":
        return ModelLoadStart(model_instance_id=str(data.get("model_instance_id", "")))
    if event_type == "model_load.progress":
        return ModelLoadProgress(progress=float(data.get("progress", 0.0)))
    if event_type == "model_load.end":
        return ModelLoadEnd(load_time_seconds=float(data.get("load_time_seconds", 0.0)))
    if event_type == "prompt_processing.start":
        return PromptProcessingStart()
    if event_type == "prompt_processing.progress":
        return PromptProcessingProgress(progress=float(data.get("progress", 0.0)))
    if event_type == "prompt_processing.end":
        return PromptProcessingEnd()
    if event_type == "message.start":
        return MessageStart()
    if event_type == "message.delta":
        return MessageDelta(content=str(data.get("content", "")))
    if event_type == "message.end":
        return MessageEnd()
    if event_type == "error":
        # `error` payload shape varies — sometimes a string, sometimes
        # `{message, ...}`. Coerce defensively.
        err = data.get("error", data.get("message", ""))
        if isinstance(err, dict):
            err = err.get("message", str(err))
        return StreamError(message=str(err))
    if event_type == "chat.end":
        result = data.get("result", {}) if isinstance(data.get("result"), dict) else {}
        usage = result.get("usage", {}) if isinstance(result.get("usage"), dict) else {}
        return ChatEnd(
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            total_time_seconds=float(result.get("total_time_seconds", 0.0)),
        )
    # Unknown event — silently skip. Reasoning / tool_call events
    # land here today; we'll add handlers when a flow needs them.
    return None


__all__ = [
    "NativeChatError",
    "lmstudio_models_url",
    "lmstudio_native_url",
    "native_chat",
]
