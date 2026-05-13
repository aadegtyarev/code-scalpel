"""Typed events from LM Studio's native `/api/v1/chat` streaming endpoint.

The OpenAI-compat endpoint (`/v1/chat/completions`) emits only text
deltas + an optional usage chunk at the end. The native endpoint
emits twenty event types covering model load progress, prompt
processing progress, reasoning, tool calls, and message content.
For an agent that wants to render «what's actually happening right
now», that's the difference between «◌ thinking…» and a real
phase bar.

We model each event as a frozen dataclass; the adapter yields a
union over these as the stream progresses. Callers
(`OperationCard` in particular) inspect `type` (via isinstance)
to render the right phase.

Reference (LM Studio docs): twenty events, sequence
  chat.start → [model_load.{start,progress,end}] →
  [prompt_processing.{start,progress,end}] →
  [reasoning.{start,delta,end} | tool_call.{start,arguments,
  success,failure}] → message.{start,delta,end} → chat.end

We don't model every one of those today — only the ones with a UI
or correctness implication. `reasoning.*` and `tool_call.*` will
be added when we wire the native endpoint into a flow that uses
them (UpstreamForker doesn't; debug_pass eventually might).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChatStart:
    """Stream initiation. Carries the instance id the server picked
    so callers can correlate with unload later."""

    model_instance_id: str


@dataclass(frozen=True)
class ModelLoadStart:
    """Cold-load begins. Triggered only on the first chat request
    to a model that isn't currently resident in memory."""

    model_instance_id: str


@dataclass(frozen=True)
class ModelLoadProgress:
    """A fraction of the load done, in [0..1]. Updates arrive
    several times during a cold load; UI redraws a phase bar."""

    progress: float


@dataclass(frozen=True)
class ModelLoadEnd:
    """Cold-load finished. `load_time_seconds` is the actual wall
    time the server spent loading the model — useful both for the
    UI badge and for calibrating expectations next time."""

    load_time_seconds: float


@dataclass(frozen=True)
class PromptProcessingStart:
    """Token processing begins. Empty payload; the start marker is
    what UI needs to switch the active phase."""


@dataclass(frozen=True)
class PromptProcessingProgress:
    """Fraction of the prompt processed, in [0..1]. On long
    prompts (8k+ tokens) this is the slowest visible step before
    generation starts."""

    progress: float


@dataclass(frozen=True)
class PromptProcessingEnd:
    """Prompt fully ingested; generation about to begin."""


@dataclass(frozen=True)
class MessageStart:
    """Response generation begins. UI switches to the streaming
    text phase."""


@dataclass(frozen=True)
class MessageDelta:
    """One chunk of generated text. Matches the role of the
    `StreamChunk(text=…)` we already emit from the OpenAI-compat
    path — the OperationCard's `generating` phase consumes this."""

    content: str


@dataclass(frozen=True)
class MessageEnd:
    """Response generation complete."""


@dataclass(frozen=True)
class StreamError:
    """Runtime error from the server. The adapter raises a
    `NativeChatError` after yielding this; callers can either show
    the error in-card or rethrow."""

    message: str


@dataclass(frozen=True)
class ChatEnd:
    """Stream conclusion. Carries aggregated stats so callers don't
    have to count deltas themselves. Token totals from this event
    feed Session bookkeeping the same way `StreamUsage` does."""

    prompt_tokens: int
    completion_tokens: int
    total_time_seconds: float


NativeStreamEvent = (
    ChatStart
    | ModelLoadStart
    | ModelLoadProgress
    | ModelLoadEnd
    | PromptProcessingStart
    | PromptProcessingProgress
    | PromptProcessingEnd
    | MessageStart
    | MessageDelta
    | MessageEnd
    | StreamError
    | ChatEnd
)


__all__ = [
    "ChatEnd",
    "ChatStart",
    "MessageDelta",
    "MessageEnd",
    "MessageStart",
    "ModelLoadEnd",
    "ModelLoadProgress",
    "ModelLoadStart",
    "NativeStreamEvent",
    "PromptProcessingEnd",
    "PromptProcessingProgress",
    "PromptProcessingStart",
    "StreamError",
]
