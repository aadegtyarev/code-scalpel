"""Минимальные тесты scripts/probes_v2/. Цель — не сломать
самые базовые контракты: пути, формат артефактов, IPC roundtrip.

Реальный прогон с LM Studio не тестируем — это сам по себе
probe-run, не unit-тест. Хотим увидеть: state-функции работают,
плейсхолдеры пишутся, IPC server-client договариваются."""

from __future__ import annotations

import asyncio
import json
import socket
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast

import pytest
import typer

from code_scalpel.llm.adapter import (
    ChatResponse,
    LLMAdapter,
    NativeToolCall,
    StreamChunk,
    StreamUsage,
)
from scripts.probes_v2.ipc import send_request, send_response, serve_request
from scripts.probes_v2.logging_adapter import LoggingLLMAdapter
from scripts.probes_v2.state import (
    RunPaths,
    append_jsonl,
    current_git_sha,
    default_metrics,
    default_verdict,
    git_remote_url,
    make_run_id,
    update_json,
    utc_now,
    write_placeholder_artifacts,
)


def test_make_run_id_shape() -> None:
    rid = make_run_id("c_fix_bug", "mini_cli", "abcdef1234567890")
    # `<scenario>-<project>-<sha7>-<timestamp>`
    assert rid.startswith("c_fix_bug-mini_cli-abcdef1-")
    # последний сегмент — YYYYMMDD-HHMMSS, ровно 15 символов
    suffix = rid.rsplit("-", 1)[-1]
    assert len(suffix) == 6  # секунды
    assert rid.count("-") >= 3


def test_default_metrics_and_verdict_shapes() -> None:
    m = default_metrics()
    assert m["user_turns"] == 0
    assert m["tool_calls_by_name"] == {}
    v = default_verdict()
    assert v["pass_score"] == 0
    assert v["criteria"] == {}


def test_write_placeholder_artifacts_creates_all(tmp_path: Path) -> None:
    """Все обязательные артефакты должны существовать после
    инициализации — даже если их содержимое будет N/A. Это
    защита от «забыли создать»."""
    paths = RunPaths(tmp_path / "run-001")
    write_placeholder_artifacts(paths)

    assert paths.chat_jsonl.exists()
    assert paths.tools_jsonl.exists()
    assert paths.timing_jsonl.exists()
    assert paths.metrics_json.exists()
    assert paths.verdict_json.exists()
    assert paths.agent_plan_md.exists()
    assert paths.user_plan_md.exists()
    assert paths.evaluation_md.exists()
    assert paths.notes_md.exists()
    assert paths.figures.is_dir()
    assert paths.final_tree.is_dir()

    # metrics.json должен парситься как JSON со схемой по дефолту
    assert json.loads(paths.metrics_json.read_text())["user_turns"] == 0


def test_append_jsonl_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    append_jsonl(path, {"ts": "now", "event": "first"})
    append_jsonl(path, {"ts": "now", "event": "second"})
    lines = path.read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["event"] == "first"
    assert json.loads(lines[1])["event"] == "second"


def test_update_json_merges_into_existing(tmp_path: Path) -> None:
    path = tmp_path / "m.json"
    path.write_text(json.dumps({"a": 1, "b": 2}))
    update_json(path, {"b": 99, "c": "new"})
    after = json.loads(path.read_text())
    assert after == {"a": 1, "b": 99, "c": "new"}


def test_utc_now_iso_with_z() -> None:
    ts = utc_now()
    # 2026-05-13T17:30:00Z
    assert ts.endswith("Z")
    assert "T" in ts
    assert len(ts) == 20


def test_current_git_sha_on_repo() -> None:
    """В нашем репо `git rev-parse HEAD` должен дать sha. Если
    выкатываем тесты на машину без git — функция возвращает
    `unknown`, тоже не падает."""
    sha = current_git_sha()
    assert isinstance(sha, str)
    # Должно быть либо 40-символьное sha, либо «unknown»
    assert sha == "unknown" or len(sha) == 40


def test_git_remote_url_returns_normalised() -> None:
    """Не утверждаем что remote есть — тесты могут гоняться в
    форке без origin. Проверяем что результат либо None, либо
    строка похожая на URL."""
    url = git_remote_url()
    assert url is None or url.startswith(("http://", "https://", "git@"))


# ── IPC ──────────────────────────────────────────────────────────


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_ipc_round_trip() -> None:
    """Поднимаем минимальный server, шлём запрос через
    send_request, проверяем что server получил и ответил."""
    port = _pick_free_port()

    received: dict[str, object] = {}

    def server_thread() -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
            srv.setsockopt(socket.SOL_SOCKET, socket.SOL_SOCKET, 0)
            srv.bind(("127.0.0.1", port))
            srv.listen(1)
            srv.settimeout(5.0)
            client, _ = srv.accept()
            with client:
                request = serve_request(client)
                received.update(request or {})
                send_response(client, {"ok": True, "echo": request})

    import threading

    th = threading.Thread(target=server_thread, daemon=True)
    th.start()

    # Дать серверу секунду подняться
    import time as _time

    _time.sleep(0.1)

    response = send_request("127.0.0.1", port, {"op": "step", "text": "hi"})
    th.join(timeout=2.0)

    assert response["ok"] is True
    assert received["op"] == "step"
    assert received["text"] == "hi"


def test_ipc_empty_response() -> None:
    """Если соединение закрылось без ответа — send_request
    возвращает ok=False с явной ошибкой, не висит."""
    port = _pick_free_port()

    def server_thread() -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
            srv.bind(("127.0.0.1", port))
            srv.listen(1)
            srv.settimeout(5.0)
            client, _ = srv.accept()
            client.close()  # мгновенно закрываем

    import threading
    import time as _time

    th = threading.Thread(target=server_thread, daemon=True)
    th.start()
    _time.sleep(0.1)

    response = send_request("127.0.0.1", port, {"op": "step", "text": "hi"}, timeout=2.0)
    th.join(timeout=2.0)
    assert response["ok"] is False
    # Сервер закрыл сокет до ответа: либо пустой ответ, либо
    # ConnectionResetError — caller должен преобразовать любой
    # в ok=False с явным error.
    error = response.get("error", "")
    assert "empty" in error or "ConnectionReset" in error or "ipc" in error


@pytest.mark.asyncio
async def test_no_op_pytest_async_works() -> None:
    """sanity — pytest-asyncio в репо настроен. Если этот тест
    не запустился, в test_probes_v2 что-то с конфигом."""
    await asyncio.sleep(0)
    assert True


# ─── LoggingLLMAdapter diagnostics ───────────────────────────────────────
#
# Reality-разбор v0.8 (главы 36/38 девлога): chat.jsonl показывал
# `tool_calls=[]` на всех response entries, но metrics.json пишет
# write_file:11. Логи теряли streaming-tool-call события. Здесь —
# unit-тесты которые проверяют, что **на текущем main** writer
# действительно записывает tool_calls и для streaming, и для non-
# streaming пути. Если красные — фиксим writer. Если зелёные —
# проблема была в historical коде, текущий main пишет логи правильно.


class _FakeAdapter:
    """Минимальный LLMAdapter для теста: возвращает заранее
    подготовленные chunks из stream() и заготовленный ChatResponse
    из chat()."""

    def __init__(
        self,
        *,
        stream_chunks: list[StreamChunk] | None = None,
        chat_response: ChatResponse | None = None,
    ) -> None:
        self._stream_chunks = stream_chunks or []
        self._chat_response = chat_response

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        assert self._chat_response is not None
        return self._chat_response

    def stream(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        return self._iter()

    async def _iter(self) -> AsyncIterator[StreamChunk]:
        for c in self._stream_chunks:
            yield c

    def set_model(self, model: str) -> None:
        pass


@pytest.mark.asyncio
async def test_logging_adapter_records_streamed_tool_calls(tmp_path: Path) -> None:
    """Когда `stream()` yieldит `StreamChunk(tool_call=...)`,
    writer должен записать его в response entry chat.jsonl как
    {id, name, arguments}. Если этот тест падает — мы воспроизвели
    дыру логирования из v0.8 (см. главу 38)."""
    chat_log = tmp_path / "chat.jsonl"
    inner = _FakeAdapter(
        stream_chunks=[
            StreamChunk(text="Понял, пишу файл. "),
            StreamChunk(
                tool_call=NativeToolCall(
                    id="call_1",
                    name="write_file",
                    arguments='{"path":"a.py","content":"x=1\\n"}',
                )
            ),
            StreamChunk(usage=StreamUsage(prompt_tokens=100, completion_tokens=20)),
        ],
    )
    adapter = LoggingLLMAdapter(cast(LLMAdapter, inner), chat_log)
    # Just drain the stream — caller would yield each chunk to StepAgent.
    chunks: list[StreamChunk] = []
    async for c in adapter.stream([{"role": "user", "content": "сделай файл"}], tools=[]):
        chunks.append(c)

    lines = [json.loads(line) for line in chat_log.read_text().splitlines()]
    # Find the response entry — there should be exactly one for the stream call.
    response_entries = [e for e in lines if e.get("role") == "response"]
    assert len(response_entries) == 1, response_entries
    entry = response_entries[0]
    assert entry["tool_calls"] == [
        {
            "id": "call_1",
            "name": "write_file",
            "arguments": '{"path":"a.py","content":"x=1\\n"}',
        }
    ], entry
    assert entry["content"] == "Понял, пишу файл. "
    assert entry["prompt_tokens"] == 100
    assert entry["completion_tokens"] == 20


@pytest.mark.asyncio
async def test_logging_adapter_records_non_streaming_tool_calls(tmp_path: Path) -> None:
    """Контрольный тест для non-streaming пути: `chat()` возвращает
    `ChatResponse` с непустым `tool_calls` — writer должен их
    записать."""
    chat_log = tmp_path / "chat.jsonl"
    inner = _FakeAdapter(
        chat_response=ChatResponse(
            content="готово",
            prompt_tokens=50,
            completion_tokens=10,
            cost=None,
            tool_calls=(
                NativeToolCall(id="c1", name="project_map", arguments="{}"),
                NativeToolCall(id="c2", name="read_file", arguments='{"path":"x.py"}'),
            ),
        ),
    )
    adapter = LoggingLLMAdapter(cast(LLMAdapter, inner), chat_log)
    response = await adapter.chat([{"role": "user", "content": "посмотри"}], tools=[])
    assert len(response.tool_calls) == 2

    lines = [json.loads(line) for line in chat_log.read_text().splitlines()]
    response_entries = [e for e in lines if e.get("role") == "response"]
    assert len(response_entries) == 1
    entry = response_entries[0]
    assert entry["tool_calls"] == [
        {"id": "c1", "name": "project_map", "arguments": "{}"},
        {"id": "c2", "name": "read_file", "arguments": '{"path":"x.py"}'},
    ]


def test_preflight_blocks_when_lmstudio_busy(monkeypatch: pytest.MonkeyPatch) -> None:
    """The CLI must refuse `step` / `go` if LM Studio is already
    GENERATING for a previous request. Otherwise the new chat
    completion queues on the model, daemon timeouts cascade, and
    the operator can't tell stuck-vs-busy. Exit code 3 is the
    distinct signal."""
    from scripts.probes_v2 import cli

    monkeypatch.setattr(cli, "_preflight_busy_check", cli._preflight_busy_check)
    # is_busy lives in code_scalpel.llm.lmstudio_status; patch there
    # so the preflight import picks up the fake.
    import code_scalpel.llm.lmstudio_status as status_mod

    monkeypatch.setattr(status_mod, "is_busy", lambda model_id=None, timeout=5.0: True)

    with pytest.raises(typer.Exit) as exc:
        cli._preflight_busy_check()
    assert exc.value.exit_code == 3


def test_preflight_allows_when_lmstudio_idle(monkeypatch: pytest.MonkeyPatch) -> None:
    """When `is_busy` says False — model is idle — preflight is a
    no-op, no exit."""
    import code_scalpel.llm.lmstudio_status as status_mod
    from scripts.probes_v2 import cli

    monkeypatch.setattr(status_mod, "is_busy", lambda model_id=None, timeout=5.0: False)
    # Should not raise.
    cli._preflight_busy_check()


def test_preflight_allows_when_lms_cli_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """No `lms` CLI on PATH → is_busy returns None → preflight
    proceeds. The caller can't act on the signal anyway, so we
    don't gate on it. If they actually do have LM Studio busy,
    they'll see the symptom at the daemon-timeout level."""
    import code_scalpel.llm.lmstudio_status as status_mod
    from scripts.probes_v2 import cli

    monkeypatch.setattr(status_mod, "is_busy", lambda model_id=None, timeout=5.0: None)
    cli._preflight_busy_check()


@pytest.mark.asyncio
async def test_logging_adapter_records_empty_tool_calls_when_text_only(
    tmp_path: Path,
) -> None:
    """Sanity: если модель ответила text-only без tool_calls — entry
    должен содержать пустой `tool_calls: []`. Защита от того, чтобы
    мы не пропустили field вовсе."""
    chat_log = tmp_path / "chat.jsonl"
    inner = _FakeAdapter(
        stream_chunks=[
            StreamChunk(text="Шаг 1. "),
            StreamChunk(text="Шаг 2."),
            StreamChunk(usage=StreamUsage(prompt_tokens=20, completion_tokens=5)),
        ],
    )
    adapter = LoggingLLMAdapter(cast(LLMAdapter, inner), chat_log)
    async for _ in adapter.stream([{"role": "user", "content": "objyasni"}], tools=[]):
        pass

    lines = [json.loads(line) for line in chat_log.read_text().splitlines()]
    response_entries = [e for e in lines if e.get("role") == "response"]
    assert len(response_entries) == 1
    assert response_entries[0]["tool_calls"] == []
    assert response_entries[0]["content"] == "Шаг 1. Шаг 2."
