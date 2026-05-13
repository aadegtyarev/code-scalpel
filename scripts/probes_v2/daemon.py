"""Background process that owns a scalpel `Runtime` for one probe run.

Single-process, single-threaded: TCP server on loopback accepts
one JSON-line request at a time, routes to the right handler,
sends one JSON-line response. CLI clients (`probe step/note/...`)
are short-lived — they connect, send, receive, disconnect.

Lifecycle:
- launched by `cli start` via subprocess (`python -m scripts.probes_v2.daemon <run-dir>`)
- writes `<run-dir>/.daemon.json` with `{pid, port}` for the CLI to find
- listens until `op=stop` comes in or process is killed
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import socket
import sys
import time
from pathlib import Path
from typing import Any

from code_scalpel.agent import ToolExecuted
from code_scalpel.config import load_config
from code_scalpel.runtime import Runtime
from code_scalpel.tools.agent_tools import ToolCall, ToolResult
from scripts.probes_v2.ipc import send_response, serve_request
from scripts.probes_v2.logging_adapter import LoggingLLMAdapter
from scripts.probes_v2.state import RunPaths, append_jsonl, update_json, utc_now


class ProbeDaemon:
    """Owns one Runtime + counters + the TCP server. Sequential
    request handling — scalpel is async but we serialize so the
    user sees deterministic order on the wire."""

    def __init__(self, run_dir: Path, workdir: Path) -> None:
        self.paths = RunPaths(run_dir)
        self.workdir = workdir
        # load_config() читает SYSTEM_CONFIG + PROJECT_CONFIG из
        # текущего CWD — CLI запускает демон с CWD=repo_root, так
        # что мы получим scalpel-конфиг основного репо. Fixture
        # своего конфига не несёт.
        self.config = load_config()
        self.logging_adapter: LoggingLLMAdapter | None = None
        self.runtime: Runtime | None = None
        self.started_at = time.monotonic()
        self.tool_calls_by_name: dict[str, int] = {}
        self.tool_calls_total = 0
        self.user_turns = 0
        self.shutdown_requested = False

    def _on_tool_executed(self, call: ToolCall, result: ToolResult) -> None:
        """Hook from StepAgent — пишем каждый tool в tools.jsonl
        и накапливаем счётчики."""
        self.tool_calls_total += 1
        self.tool_calls_by_name[call.name] = self.tool_calls_by_name.get(call.name, 0) + 1
        append_jsonl(
            self.paths.tools_jsonl,
            {
                "ts": utc_now(),
                "name": call.name,
                "args": call.body,
                "output": result.output,
                "ok": result.ok,
                "diff": result.diff,
            },
        )

    def _init_runtime(self) -> None:
        """Lazy: только когда первый step придёт. Пинит модель к
        `PROBE_BASE_MODEL` (выставляется CLI'ем) — никаких `auto`,
        нужна явная id для reproducibility прогонов. Если задан
        `PROBE_UPSTREAM_MODEL` — создаём UpstreamProfile для
        делегирования сложных fork'ов."""
        from code_scalpel.fork import UpstreamProfile
        from code_scalpel.llm.adapter import OpenAICompatibleAdapter

        # Пин основной модели. Mutation модели в pydantic-объекте
        # допустима — модель не frozen.
        pinned = os.environ.get("PROBE_BASE_MODEL")
        profile = self.config.current_profile
        if pinned:
            profile.model = pinned
        base_llm = OpenAICompatibleAdapter(
            base_url=f"{profile.provider_base_url()}/v1",
            api_key=profile.api_key(),
            model=profile.model,
            timeout=float(self.config.agent.llm_timeout),
            cost_per_1k=profile.cost_per_1k,
        )
        self.logging_adapter = LoggingLLMAdapter(base_llm, self.paths.chat_jsonl)

        upstream_model = os.environ.get("PROBE_UPSTREAM_MODEL")
        upstream_profile = None
        if upstream_model:
            # v0.12 UpstreamProfile — отдельная конфигурация для
            # делегирования сложных fork'ов. Базовый URL тот же
            # (LM Studio свопает модели через `state: loaded`),
            # но другая модель = upstream.
            upstream_profile = UpstreamProfile(
                base_url=f"{profile.provider_base_url()}/v1",
                model=upstream_model,
            )

        runtime = Runtime(
            cwd=self.workdir,
            config=self.config,
            llm=self.logging_adapter,
            with_memory=False,  # probe не должен подцеплять memory из workdir
            upstream_profile=upstream_profile,
        )
        self.runtime = runtime

    async def handle_step(self, text: str, mode: str) -> dict[str, Any]:
        """Один turn диалога в указанном mode.

        Mode-routing:
          - `ask` / `plan` / `review` → `agent.ask` со mode-аддендумом.
            Это объяснительный/обсуждающий режим — модель отвечает
            текстом, опционально дёргает tools, не патчит автоматом.
          - `code` → `agent.code_with_retry(mode="code", force_loop=True)`.
            Iterative patch loop с retry, плюс post-write валидация.
            Реальный «делать»-режим.
        """
        if self.runtime is None:
            self._init_runtime()
        assert self.runtime is not None
        self.user_turns += 1
        append_jsonl(
            self.paths.chat_jsonl,
            {
                "ts": utc_now(),
                "role": "user",
                "content": text,
                "turn": self.user_turns,
                "mode": mode,
            },
        )
        append_jsonl(
            self.paths.timing_jsonl,
            {"ts": utc_now(), "event": "step.start", "turn": self.user_turns, "mode": mode},
        )
        # Channel-unification: prepare_turn в демоне вручную — глава
        # 17 девлога. См. PROTOCOL.md «Текущие ограничения runner'а».
        task = self.runtime.session.prepare_turn(text)
        tool_events: list[ToolExecuted] = []

        def _hook(call: ToolCall, result: ToolResult) -> None:
            self._on_tool_executed(call, result)
            tool_events.append(ToolExecuted(call=call, result=result))

        try:
            if mode == "code":
                step_result = await self.runtime.agent.code_with_retry(
                    task,
                    mode="code",
                    on_tool_executed=_hook,
                    force_loop=True,
                )
            else:
                step_result = await self.runtime.agent.ask(task, mode=mode, on_tool_executed=_hook)
        except Exception as e:  # noqa: BLE001 — клиенту нужен любой fail с reason'ом
            append_jsonl(
                self.paths.timing_jsonl,
                {"ts": utc_now(), "event": "step.error", "error": repr(e)},
            )
            return {"ok": False, "error": str(e)}
        append_jsonl(
            self.paths.timing_jsonl,
            {"ts": utc_now(), "event": "step.end", "turn": self.user_turns},
        )
        return {
            "ok": True,
            "reply": step_result.reply,
            "tool_calls": len(tool_events),
        }

    async def handle_go(self) -> dict[str, Any]:
        """Запускает `agent.run_plan` на TASKS.md в workdir. Это
        отдельная команда (не turn): scalpel сам идёт по плану в
        code mode с iterative patch loop, мы не пишем реплики."""
        if self.runtime is None:
            self._init_runtime()
        assert self.runtime is not None
        append_jsonl(self.paths.timing_jsonl, {"ts": utc_now(), "event": "go.start"})
        append_jsonl(
            self.paths.chat_jsonl,
            {"ts": utc_now(), "role": "user", "content": "/go", "turn": None, "mode": "code"},
        )

        def _hook(call: ToolCall, result: ToolResult) -> None:
            self._on_tool_executed(call, result)

        try:
            result = await self.runtime.agent.run_plan(
                on_tool_executed=_hook,
                fork_resolver=self.runtime.fork_resolver,
            )
        except Exception as e:  # noqa: BLE001
            append_jsonl(
                self.paths.timing_jsonl,
                {"ts": utc_now(), "event": "go.error", "error": repr(e)},
            )
            return {"ok": False, "error": str(e)}
        append_jsonl(
            self.paths.timing_jsonl,
            {
                "ts": utc_now(),
                "event": "go.end",
                "stopped_reason": result.stopped_reason,
                "tasks_completed": result.tasks_completed,
            },
        )
        return {
            "ok": True,
            "stopped_reason": result.stopped_reason,
            "tasks_completed": result.tasks_completed,
            "outcomes": [{"task_id": o.task.id, "status": o.status} for o in result.outcomes],
        }

    def handle_note(self, text: str) -> dict[str, Any]:
        ts = utc_now()
        with self.paths.notes_md.open("a", encoding="utf-8") as fh:
            fh.write(f"\n## {ts}\n\n{text}\n")
        return {"ok": True}

    def handle_status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "user_turns": self.user_turns,
            "tool_calls_total": self.tool_calls_total,
            "wall_time_sec": time.monotonic() - self.started_at,
            "llm_requests": self.logging_adapter.requests if self.logging_adapter else 0,
        }

    def handle_stop(self) -> dict[str, Any]:
        """Финализирует артефакты которые знает демон. Снимок
        final_tree и tar.gz + INDEX-update делает CLI после
        получения подтверждения остановки — workdir вне репо,
        демону туда не лезть."""
        self.shutdown_requested = True
        wall = time.monotonic() - self.started_at
        metrics_update: dict[str, Any] = {
            "user_turns": self.user_turns,
            "tool_calls_total": self.tool_calls_total,
            "tool_calls_by_name": self.tool_calls_by_name,
            "wall_time_sec": round(wall, 2),
        }
        if self.logging_adapter is not None:
            metrics_update["agent_llm_requests"] = self.logging_adapter.requests
            metrics_update["prompt_tokens_total"] = self.logging_adapter.prompt_tokens_total
            metrics_update["completion_tokens_total"] = self.logging_adapter.completion_tokens_total
            metrics_update["prompt_tokens_peak"] = self.logging_adapter.prompt_tokens_peak
        update_json(self.paths.metrics_json, metrics_update)
        return {"ok": True, "metrics": metrics_update}

    async def handle(self, payload: dict[str, Any]) -> dict[str, Any]:
        op = payload.get("op")
        if op == "step":
            text = payload.get("text", "")
            if not isinstance(text, str) or not text.strip():
                return {"ok": False, "error": "missing or empty text"}
            mode = payload.get("mode", "ask")
            if mode not in {"ask", "plan", "code", "review"}:
                return {"ok": False, "error": f"bad mode: {mode}"}
            return await self.handle_step(text, mode)
        if op == "go":
            return await self.handle_go()
        if op == "note":
            text = payload.get("text", "")
            if not isinstance(text, str) or not text.strip():
                return {"ok": False, "error": "missing or empty text"}
            return self.handle_note(text)
        if op == "status":
            return self.handle_status()
        if op == "stop":
            return self.handle_stop()
        return {"ok": False, "error": f"unknown op: {op}"}


async def serve(daemon: ProbeDaemon, host: str, port: int) -> int:
    """Принимает соединения по одному, обрабатывает синхронно
    через async-handler. Когда `shutdown_requested`, после
    ответа на текущий запрос — gracefully выходим."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((host, port))
    server.listen(4)
    server.settimeout(1.0)  # poll так чтобы можно было выйти на shutdown
    try:
        while not daemon.shutdown_requested:
            try:
                client, _ = server.accept()
            except OSError:
                continue
            try:
                request = serve_request(client)
                if request is None:
                    send_response(client, {"ok": False, "error": "empty request"})
                else:
                    response = await daemon.handle(request)
                    send_response(client, response)
            finally:
                client.close()
    finally:
        server.close()
    return 0


def _pick_port() -> int:
    """OS-assigned port на loopback. Используем temp socket, чтобы
    узнать порт, потом отдадим в serve."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: python -m scripts.probes_v2.daemon <run-dir> <workdir>", file=sys.stderr)
        return 2
    run_dir = Path(argv[1]).resolve()
    workdir = Path(argv[2]).resolve()
    if not run_dir.is_dir() or not workdir.is_dir():
        print(f"error: missing dirs: run_dir={run_dir} workdir={workdir}", file=sys.stderr)
        return 2

    daemon = ProbeDaemon(run_dir, workdir)
    port = _pick_port()
    daemon.paths.daemon_info.write_text(
        json.dumps({"pid": os.getpid(), "host": "127.0.0.1", "port": port}) + "\n"
    )
    try:
        return asyncio.run(serve(daemon, "127.0.0.1", port))
    finally:
        # При выходе подчищаем daemon-info, чтобы клиент не пытался
        # коннектиться к мёртвому порту. Workdir остаётся — CLI
        # finalize забирает снапшот и сам прибирает.
        with contextlib.suppress(OSError):
            daemon.paths.daemon_info.unlink()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
