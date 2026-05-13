"""Native LM Studio adapter — typed-event SSE consumer.

Tests the URL-derivation helpers and the SSE parser through a
mocked HTTP transport. No live LM Studio required — the response
body is a hand-crafted byte stream of `data: {json}\n` lines that
mirrors what the docs say the server emits.
"""

from __future__ import annotations

import httpx
import pytest

from code_scalpel.llm.lmstudio_native import (
    NativeChatError,
    _parse_sse_event,
    lmstudio_models_url,
    lmstudio_native_url,
    native_chat,
)
from code_scalpel.llm.native_events import (
    ChatEnd,
    ChatStart,
    MessageDelta,
    ModelLoadEnd,
    ModelLoadProgress,
    PromptProcessingProgress,
    StreamError,
)


def test_native_url_derivation() -> None:
    """The OpenAI-compat base URL ends in /v1; native lives at the
    root /api/v1/chat. Tests cover the three common shapes."""
    assert lmstudio_native_url("http://localhost:1234/v1") == "http://localhost:1234/api/v1/chat"
    assert lmstudio_native_url("http://localhost:1234/v1/") == "http://localhost:1234/api/v1/chat"
    assert (
        lmstudio_native_url("https://lms.example.com:8443/v1")
        == "https://lms.example.com:8443/api/v1/chat"
    )


def test_models_url_derivation() -> None:
    assert lmstudio_models_url("http://localhost:1234/v1") == "http://localhost:1234/api/v1/models"


def test_parse_sse_skips_empty_and_done() -> None:
    """Blank lines, comments, the `[DONE]` sentinel — all return
    None so the loop can move on without surfacing noise."""
    assert _parse_sse_event("") is None
    assert _parse_sse_event("  \n") is None
    assert _parse_sse_event("data: [DONE]") is None
    assert _parse_sse_event(": this is a comment") is None


def test_parse_sse_unknown_event_returns_none() -> None:
    """A future server adds a new event type — we silently skip
    instead of crashing. The contract is `subset of known events`."""
    assert _parse_sse_event('data: {"type": "future_event_we_dont_know"}') is None


def test_parse_chat_start() -> None:
    ev = _parse_sse_event('data: {"type": "chat.start", "model_instance_id": "abc"}')
    assert isinstance(ev, ChatStart)
    assert ev.model_instance_id == "abc"


def test_parse_model_load_progress() -> None:
    ev = _parse_sse_event('data: {"type": "model_load.progress", "progress": 0.42}')
    assert isinstance(ev, ModelLoadProgress)
    assert ev.progress == pytest.approx(0.42)


def test_parse_model_load_end() -> None:
    ev = _parse_sse_event('data: {"type": "model_load.end", "load_time_seconds": 12.5}')
    assert isinstance(ev, ModelLoadEnd)
    assert ev.load_time_seconds == pytest.approx(12.5)


def test_parse_prompt_processing_progress() -> None:
    ev = _parse_sse_event('data: {"type": "prompt_processing.progress", "progress": 0.75}')
    assert isinstance(ev, PromptProcessingProgress)
    assert ev.progress == pytest.approx(0.75)


def test_parse_message_delta() -> None:
    ev = _parse_sse_event('data: {"type": "message.delta", "content": "Hello, "}')
    assert isinstance(ev, MessageDelta)
    assert ev.content == "Hello, "


def test_parse_error_event_with_string_payload() -> None:
    """Error payloads are inconsistent across server versions —
    sometimes a string under `error`, sometimes a dict with
    `message`. Coerce to a string either way."""
    ev = _parse_sse_event('data: {"type": "error", "error": "out of memory"}')
    assert isinstance(ev, StreamError)
    assert "out of memory" in ev.message


def test_parse_error_event_with_dict_payload() -> None:
    ev = _parse_sse_event('data: {"type": "error", "error": {"message": "context too long"}}')
    assert isinstance(ev, StreamError)
    assert "context too long" in ev.message


def test_parse_chat_end_picks_usage_from_result() -> None:
    """`chat.end` carries the aggregated stats in a nested `result.usage`
    object. Adapter unwraps so the Session can consume token totals
    without knowing the SSE shape."""
    ev = _parse_sse_event(
        'data: {"type": "chat.end", "result": '
        '{"usage": {"prompt_tokens": 800, "completion_tokens": 50}, '
        '"total_time_seconds": 4.2}}'
    )
    assert isinstance(ev, ChatEnd)
    assert ev.prompt_tokens == 800
    assert ev.completion_tokens == 50
    assert ev.total_time_seconds == pytest.approx(4.2)


@pytest.mark.asyncio
async def test_native_chat_emits_full_event_timeline() -> None:
    """End-to-end: feed a hand-crafted SSE byte stream through a
    mocked httpx transport. Verify the adapter yields one event per
    line, in order, mapped to the right dataclass."""
    sse_body = (
        b'data: {"type": "chat.start", "model_instance_id": "i1"}\n'
        b'data: {"type": "model_load.start", "model_instance_id": "i1"}\n'
        b'data: {"type": "model_load.progress", "progress": 0.5}\n'
        b'data: {"type": "model_load.end", "load_time_seconds": 8.0}\n'
        b'data: {"type": "prompt_processing.start"}\n'
        b'data: {"type": "prompt_processing.end"}\n'
        b'data: {"type": "message.start"}\n'
        b'data: {"type": "message.delta", "content": "hi"}\n'
        b'data: {"type": "message.end"}\n'
        b'data: {"type": "chat.end", "result": {"usage": '
        b'{"prompt_tokens": 10, "completion_tokens": 2}, '
        b'"total_time_seconds": 12.0}}\n'
        b"data: [DONE]\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=sse_body,
            headers={"content-type": "text/event-stream"},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        events: list[object] = []
        async for ev in native_chat(
            base_url="http://localhost:1234/v1",
            model="qwen-test",
            messages=[{"role": "user", "content": "hi"}],
            client=client,
        ):
            events.append(ev)

    types = [type(e).__name__ for e in events]
    assert types == [
        "ChatStart",
        "ModelLoadStart",
        "ModelLoadProgress",
        "ModelLoadEnd",
        "PromptProcessingStart",
        "PromptProcessingEnd",
        "MessageStart",
        "MessageDelta",
        "MessageEnd",
        "ChatEnd",
    ]


@pytest.mark.asyncio
async def test_native_chat_raises_on_http_error() -> None:
    """Non-2xx HTTP → NativeChatError with status + body excerpt
    so the operator sees what the server actually said. Probe/CI
    runs depend on this — silent failure would mask a misconfigured
    LM Studio."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="server boom")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(NativeChatError) as exc:
            async for _ in native_chat(
                base_url="http://localhost:1234/v1",
                model="x",
                messages=[{"role": "user", "content": "hi"}],
                client=client,
            ):
                pass
    assert "500" in str(exc.value)
    assert "server boom" in str(exc.value)


@pytest.mark.asyncio
async def test_native_chat_passes_ttl_when_set() -> None:
    """`ttl_seconds` is the native-only knob that tells LM Studio
    how long the model lingers after the request. Other adapters
    don't have it; we have to make sure it lands in the request
    body when set."""
    captured_body: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        captured_body.update(_json.loads(request.content))
        return httpx.Response(
            200,
            content=b'data: {"type": "chat.end", "result": {}}\n',
            headers={"content-type": "text/event-stream"},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        async for _ in native_chat(
            base_url="http://localhost:1234/v1",
            model="x",
            messages=[{"role": "user", "content": "hi"}],
            ttl_seconds=300,
            client=client,
        ):
            pass

    assert captured_body["ttl"] == 300
    assert captured_body["stream"] is True
