"""Tests for the LM Studio runtime status helper.

We don't shell out to a real `lms ps` here — those tests would
require LM Studio installed and a model loaded. The parser is the
hot spot (multi-word fields like `8.99 GB` confuse naive split),
so we cover it directly with table snapshots, and exercise the
`is_busy()` surface with a monkey-patched `list_loaded`."""

from __future__ import annotations

from code_scalpel.llm.lmstudio_status import (
    InstanceStatus,
    _parse_lms_ps,
    cancel_generation,
    is_busy,
    list_loaded,
)


def test_parse_lms_ps_generating() -> None:
    """Real captured output, 2026-05-14, model actively generating."""
    output = (
        "IDENTIFIER                MODEL                     STATUS        "
        "SIZE       CONTEXT    PARALLEL    DEVICE    TTL\n"
        "qwen/qwen2.5-coder-14b    qwen/qwen2.5-coder-14b    GENERATING    "
        "8.99 GB    16384      1           Local\n"
    )
    rows = _parse_lms_ps(output)
    assert len(rows) == 1
    r = rows[0]
    assert r.identifier == "qwen/qwen2.5-coder-14b"
    assert r.model == "qwen/qwen2.5-coder-14b"
    assert r.status == "GENERATING"
    assert r.size == "8.99 GB"
    assert r.context == "16384"
    assert r.parallel == "1"
    assert r.device == "Local"


def test_parse_lms_ps_loaded() -> None:
    """Same shape, status=LOADED instead — model idle."""
    output = (
        "IDENTIFIER                MODEL                     STATUS    "
        "SIZE       CONTEXT    PARALLEL    DEVICE    TTL\n"
        "qwen/qwen2.5-coder-14b    qwen/qwen2.5-coder-14b    LOADED    "
        "8.99 GB    16384      1           Local\n"
    )
    rows = _parse_lms_ps(output)
    assert len(rows) == 1
    assert rows[0].status == "LOADED"


def test_parse_lms_ps_unknown_status() -> None:
    """Future LM Studio status string we haven't seen — should map
    to UNKNOWN so callers don't false-positive on a typo."""
    output = (
        "IDENTIFIER                MODEL                     STATUS         "
        "SIZE       CONTEXT    PARALLEL    DEVICE    TTL\n"
        "qwen/qwen2.5-coder-14b    qwen/qwen2.5-coder-14b    HIBERNATING    "
        "8.99 GB    16384      1           Local\n"
    )
    rows = _parse_lms_ps(output)
    assert len(rows) == 1
    assert rows[0].status == "UNKNOWN"


def test_parse_lms_ps_empty() -> None:
    """No models loaded — `lms ps` returns just the header. Parser
    returns an empty list, not crash."""
    output = "IDENTIFIER    MODEL    STATUS    SIZE    CONTEXT    PARALLEL    DEVICE    TTL\n"
    assert _parse_lms_ps(output) == []


def test_parse_lms_ps_no_header() -> None:
    """Defensive: if upstream format changes and the header line is
    missing/different, return empty rather than mis-parse a warning
    line as a row."""
    output = "warning: lms cli outdated, please update\n"
    assert _parse_lms_ps(output) == []


def test_is_busy_returns_none_when_lms_missing(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """If `lms` CLI is not on PATH (production users without LM
    Studio installed), is_busy returns None — caller can choose to
    treat as 'unknown, proceed'."""
    import code_scalpel.llm.lmstudio_status as mod

    monkeypatch.setattr(mod, "_find_lms_binary", lambda: None)
    assert is_busy() is None
    assert list_loaded() is None


def test_is_busy_returns_true_when_any_generating(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Multi-model setup: even one GENERATING instance means the
    server is busy, because a new chat request will queue."""
    import code_scalpel.llm.lmstudio_status as mod

    fake = [
        InstanceStatus(
            identifier="model-a",
            model="model-a",
            status="LOADED",
            size="3 GB",
            context="4096",
            parallel="1",
            device="Local",
            ttl="",
        ),
        InstanceStatus(
            identifier="model-b",
            model="model-b",
            status="GENERATING",
            size="9 GB",
            context="16384",
            parallel="1",
            device="Local",
            ttl="",
        ),
    ]
    monkeypatch.setattr(mod, "list_loaded", lambda timeout=5.0: fake)
    assert is_busy() is True
    # Per-model query gets only that model's status.
    assert is_busy(model_id="model-a") is False
    assert is_busy(model_id="model-b") is True


def test_is_busy_returns_false_when_no_models_loaded(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """No instances → not busy (and caller can decide whether to
    load one or fail). Different from None — we *know* it's idle."""
    import code_scalpel.llm.lmstudio_status as mod

    monkeypatch.setattr(mod, "list_loaded", lambda timeout=5.0: [])
    assert is_busy() is False


def test_parse_lms_ps_idle_status() -> None:
    """After `lms unload && lms load`, the model reports IDLE
    instead of LOADED. Same meaning (ready, not busy) — both must
    map to a known non-GENERATING status, not UNKNOWN."""
    output = (
        "IDENTIFIER                MODEL                     STATUS    "
        "SIZE       CONTEXT    PARALLEL    DEVICE    TTL\n"
        "qwen/qwen2.5-coder-14b    qwen/qwen2.5-coder-14b    IDLE      "
        "8.99 GB    16384      1           Local\n"
    )
    rows = _parse_lms_ps(output)
    assert len(rows) == 1
    assert rows[0].status == "IDLE"


def test_is_busy_false_for_idle(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """IDLE must read as not-busy. Otherwise post-unload + load
    sequence would falsely show 'busy' and block downstream calls."""
    import code_scalpel.llm.lmstudio_status as mod

    monkeypatch.setattr(
        mod,
        "list_loaded",
        lambda timeout=5.0: [
            InstanceStatus(
                identifier="qwen",
                model="qwen",
                status="IDLE",
                size="9 GB",
                context="16384",
                parallel="1",
                device="Local",
                ttl="",
            )
        ],
    )
    assert is_busy() is False


def test_cancel_generation_returns_none_when_lms_missing(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """No `lms` CLI on PATH → cancel returns None. Caller can
    either skip or fall back to closing the HTTP connection."""
    import code_scalpel.llm.lmstudio_status as mod

    monkeypatch.setattr(mod, "_find_lms_binary", lambda: None)
    assert cancel_generation("qwen/qwen2.5-coder-14b") is None


def test_cancel_generation_invokes_lms_unload(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """When `lms` is available, cancel shells out to
    `lms unload <model_id>`. We assert the argv shape so a future
    arg-order change doesn't pass tests but break in prod."""
    import code_scalpel.llm.lmstudio_status as mod

    captured: dict[str, object] = {}

    class _FakeResult:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(argv: list[str], **kw: object) -> _FakeResult:
        captured["argv"] = argv
        return _FakeResult()

    monkeypatch.setattr(mod, "_find_lms_binary", lambda: "/usr/local/bin/lms")
    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    assert cancel_generation("qwen/qwen2.5-coder-14b") is True
    assert captured["argv"] == ["/usr/local/bin/lms", "unload", "qwen/qwen2.5-coder-14b"]
