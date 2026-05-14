"""Tests for provider-agnostic cancel_inflight_inference routing.

Goal: each branch (lmstudio + variants / paid-provider / unknown)
returns the right CancelResult shape — and the LM Studio branch
shells out to the correct cancel_generation argv. We don't actually
invoke `lms` here — the underlying utility has its own tests."""

from __future__ import annotations

from code_scalpel.llm.cancel import cancel_inflight_inference


def test_lmstudio_unload_success(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """LM Studio + valid model_id + lms unload OK → stopped=True,
    reason=lms_unload. Caller should display the human message."""
    import code_scalpel.llm.lmstudio_status as status_mod

    monkeypatch.setattr(status_mod, "cancel_generation", lambda model_id: True)
    result = cancel_inflight_inference("lmstudio", "qwen/qwen2.5-coder-14b")
    assert result.stopped is True
    assert result.reason == "lms_unload"
    assert "qwen/qwen2.5-coder-14b" in result.message


def test_lmstudio_unload_failed(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """LM Studio + valid model_id + lms unload errored (returncode
    non-zero) → stopped=False, fallback to connection-close
    semantics."""
    import code_scalpel.llm.lmstudio_status as status_mod

    monkeypatch.setattr(status_mod, "cancel_generation", lambda model_id: False)
    result = cancel_inflight_inference("lmstudio", "qwen/qwen2.5-coder-14b")
    assert result.stopped is False
    assert result.reason == "lms_unload_failed"


def test_lmstudio_lms_cli_missing(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """LM Studio but `lms` CLI not on PATH → cancel_generation
    returns None. Caller has to live with connection-close only."""
    import code_scalpel.llm.lmstudio_status as status_mod

    monkeypatch.setattr(status_mod, "cancel_generation", lambda model_id: None)
    result = cancel_inflight_inference("lmstudio", "qwen/qwen2.5-coder-14b")
    assert result.stopped is False
    assert result.reason == "lms_cli_missing"


def test_lmstudio_without_model_id() -> None:
    """LM Studio but caller forgot to pass model_id — we can't do
    anything (lms unload needs a model). Stopped=False, distinct
    reason so probe/TUI logs are useful."""
    result = cancel_inflight_inference("lmstudio", None)
    assert result.stopped is False
    assert result.reason == "lms_missing_model"


def test_unknown_provider() -> None:
    """OpenAI / Anthropic / OpenRouter / etc — no native abort wired
    in today. We still return a result with the warning about
    billing, so TUI/probe shows the user what happened."""
    result = cancel_inflight_inference("openai", "gpt-4")
    assert result.stopped is False
    assert result.reason == "connection_close_only"
    assert "openai" in result.message.lower()
    assert "биллинг" in result.message


def test_no_provider() -> None:
    """provider=None happens when the agent isn't sure (e.g. spy
    mode, fresh init). Distinct reason so we don't mix up 'unknown
    paid provider' with 'no idea what's going on'."""
    result = cancel_inflight_inference(None, "anything")
    assert result.stopped is False
    assert result.reason == "no_provider"
