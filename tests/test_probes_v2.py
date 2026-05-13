"""Минимальные тесты scripts/probes_v2/. Цель — не сломать
самые базовые контракты: пути, формат артефактов, IPC roundtrip.

Реальный прогон с LM Studio не тестируем — это сам по себе
probe-run, не unit-тест. Хотим увидеть: state-функции работают,
плейсхолдеры пишутся, IPC server-client договариваются."""

from __future__ import annotations

import asyncio
import json
import socket
from pathlib import Path

import pytest

from scripts.probes_v2.ipc import send_request, send_response, serve_request
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
