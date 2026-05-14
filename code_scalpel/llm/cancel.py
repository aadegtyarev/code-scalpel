"""Provider-agnostic best-effort cancellation of an in-flight LLM inference.

Closing the streaming HTTP connection from the client is **not enough**
on every backend:

- **LM Studio** (local): TCP close doesn't always stop generation —
  the model can keep producing tokens until its stop-token or
  max_tokens. GPU stays busy, queue stays blocked.
- **OpenAI / OpenRouter / Anthropic** (paid): client-side abort
  *usually* stops billing per the API contract, but the implementation
  detail varies by SDK and by whether `stream` was set. Worst case:
  the server keeps generating and you keep paying for tokens you'll
  never see.

This module routes a cancellation request to the right provider-specific
mechanism:

- For LM Studio → `lms unload <model>` (hard stop, loses warm cache,
  ~5s reload on next chat call). Imperfect but **guaranteed** to free
  the GPU.
- For other providers → no native abort available today; we
  acknowledge the client closed the stream and warn the caller that
  server-side billing/work may continue briefly.

When `provider` is None or unknown, we treat as "best-effort
connection-close only" and return that reason.

Why a separate module: the TUI Esc-handler and the probe-runner
cleanup logic both call this; keeping the routing here means neither
has to know about `lms ps` or LM Studio's behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CancelReason = Literal[
    "lms_unload",
    "lms_unload_failed",
    "lms_missing_model",
    "lms_cli_missing",
    "connection_close_only",
    "no_provider",
]


@dataclass(frozen=True)
class CancelResult:
    """Outcome of a cancellation attempt.

    - `stopped` — did we cause the server-side inference to stop?
      `True` is a strong signal (LM Studio unload succeeded). `False`
      means we only closed the client connection and the server may
      still be working.
    - `reason` — machine-readable code, see CancelReason.
    - `message` — short human-readable note for the TUI footer /
      probe log."""

    stopped: bool
    reason: CancelReason
    message: str


def cancel_inflight_inference(
    provider: str | None,
    model_id: str | None,
) -> CancelResult:
    """Best-effort server-side abort. Caller is expected to have
    already cancelled the python-side task (`worker.cancel()` or
    `asyncio.Task.cancel()`) — this routine handles the *server*.

    Synchronous because the underlying paths (`lms unload`,
    connection-close-flag) don't need async — callers in async
    contexts can wrap in `asyncio.to_thread` if blocking is a
    concern (lms unload is fast, ~1s)."""
    if provider == "lmstudio":
        if not model_id:
            return CancelResult(
                stopped=False,
                reason="lms_missing_model",
                message="LM Studio: model id unknown, can't unload.",
            )
        from code_scalpel.llm.lmstudio_status import cancel_generation

        ok = cancel_generation(model_id)
        if ok is None:
            return CancelResult(
                stopped=False,
                reason="lms_cli_missing",
                message="`lms` CLI not found — close-connection only.",
            )
        if ok:
            return CancelResult(
                stopped=True,
                reason="lms_unload",
                message=f"Модель {model_id} остановлена (выгружена).",
            )
        return CancelResult(
            stopped=False,
            reason="lms_unload_failed",
            message="`lms unload` failed — close-connection only.",
        )

    if provider is None:
        return CancelResult(
            stopped=False,
            reason="no_provider",
            message="Provider unknown; close-connection only.",
        )

    # OpenAI, Anthropic, OpenRouter, others — no native abort wired
    # in scalpel today. Best we have is the client already closed the
    # stream. For paid providers this *usually* stops billing, but it
    # depends on the SDK and provider implementation. Warn the user.
    return CancelResult(
        stopped=False,
        reason="connection_close_only",
        message=(
            f"Provider {provider!r}: соединение закрыто, "
            "но биллинг может тикать до сервер-side cleanup."
        ),
    )


__all__ = ["CancelResult", "CancelReason", "cancel_inflight_inference"]
