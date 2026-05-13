"""JSON-line IPC по TCP-loopback между CLI и demon'ом.

CLI клиент шлёт `{op: "step"|"note"|"stop"|"status", ...}`,
демон отвечает `{ok: bool, ...}`. Сообщения разделены `\\n`,
кодировка utf-8. Один запрос — один ответ — клиент закрывает
соединение.

Loopback вместо unix socket потому что (a) удобнее в тестах
(можно поднять на любом порту), (b) единственный пользователь —
локальная машина, файл socket не нужен."""

from __future__ import annotations

import json
import socket
from typing import Any


def send_request(
    host: str, port: int, payload: dict[str, Any], timeout: float = 200.0
) -> dict[str, Any]:
    """Открывает TCP-соединение, шлёт JSON-line, читает один
    JSON-line ответ, закрывает. Timeout общий на соединение +
    ответ — 200 сек дефолт, под 180-сек ответ scalpel'а с
    запасом.

    Любые сетевые ошибки (reset, broken pipe, timeout, refused)
    превращаем в `{ok: False, error: "..."}` — caller'у нужен
    один формат для всего."""
    buf = b""
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
            while b"\n" not in buf:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                buf += chunk
    except (ConnectionError, TimeoutError, OSError) as e:
        if not buf:
            return {"ok": False, "error": f"ipc {type(e).__name__}: {e}"}
        # частичный ответ есть — пытаемся распарсить ниже
    line, _, _ = buf.partition(b"\n")
    if not line:
        return {"ok": False, "error": "empty response from daemon"}
    try:
        result: dict[str, Any] = json.loads(line.decode("utf-8"))
        return result
    except json.JSONDecodeError as e:
        return {"ok": False, "error": f"bad json from daemon: {e}"}


def serve_request(sock: socket.socket) -> dict[str, Any] | None:
    """Server-side: ждёт один JSON-line запрос. Возвращает
    распарсенный payload или None если клиент закрыл соединение
    без сообщения."""
    buf = b""
    sock.settimeout(60.0)
    while b"\n" not in buf:
        chunk = sock.recv(65536)
        if not chunk:
            return None if not buf else _try_parse(buf)
        buf += chunk
    line, _, _ = buf.partition(b"\n")
    return _try_parse(line)


def send_response(sock: socket.socket, payload: dict[str, Any]) -> None:
    """Server-side: шлёт один JSON-line, закрывать соединение
    после — задача caller'а."""
    sock.sendall((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))


def _try_parse(data: bytes) -> dict[str, Any] | None:
    try:
        result: dict[str, Any] = json.loads(data.decode("utf-8"))
        return result
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


__all__ = ["send_request", "send_response", "serve_request"]
