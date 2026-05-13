"""Explicit LM Studio model swap via REST.

Single-GPU machines can't hold two large models at once, so the
v0.12 upstream-delegation framework needs an actual unload/load
dance — not LM Studio's auto-evict, which is opaque and harder
to reason about in artefacts.

The swap cost is real: 5–10 seconds per `load`, less for `unload`.
We minimise it by batching — one swap brackets a whole
`flush_upstream` call (potentially N forks), not each fork.

REST endpoints we use (LM Studio 0.3+):
- `POST /api/v1/models/load`   body `{"model": "<key>"}` → `{instance_id, status, ...}`
- `POST /api/v1/models/unload` body `{"instance_id": "<id>"}` → `{instance_id}`
- `GET  /api/v1/models`        → `{models: [{key, loaded_instances, ...}]}`
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx


@dataclass(frozen=True)
class SwapConfig:
    """Where to talk to LM Studio. Derived from any OpenAI-compat
    base_url (`http://host:port/v1`) — we replace the path with the
    native `/api/v1` prefix that load/unload live under."""

    native_base: str  # e.g. http://localhost:1234/api/v1

    @classmethod
    def from_openai_base(cls, openai_compat_base: str) -> SwapConfig:
        parsed = urlparse(openai_compat_base)
        return cls(native_base=f"{parsed.scheme}://{parsed.netloc}/api/v1")


class SwapError(RuntimeError):
    """Любая ошибка load/unload. Поднимаем — пусть caller решает
    rollback'нуть состояние или просто пометить fork как failed."""


# Опциональный transport для тестов — `httpx.MockTransport(...)`. По
# умолчанию None → реальный сетевой стек. Тесты подменяют через
# `set_test_transport()`, чтобы не моньяпатчить `httpx.AsyncClient`
# (это вызвало бы рекурсию когда мы сами его инстанцируем).
_TEST_TRANSPORT: httpx.MockTransport | None = None


def set_test_transport(transport: httpx.MockTransport | None) -> None:
    global _TEST_TRANSPORT
    _TEST_TRANSPORT = transport


def _client(timeout: float) -> httpx.AsyncClient:
    if _TEST_TRANSPORT is not None:
        return httpx.AsyncClient(transport=_TEST_TRANSPORT, timeout=timeout)
    return httpx.AsyncClient(timeout=timeout)


async def loaded_instances(cfg: SwapConfig, *, timeout: float = 5.0) -> list[str]:
    """Идентификаторы всех сейчас загруженных моделей. По одной на
    инстанс — если одна модель загружена дважды, два id (хотя
    обычно у нас один-к-одному с key)."""
    async with _client(timeout) as client:
        resp = await client.get(f"{cfg.native_base}/models")
        resp.raise_for_status()
        data = resp.json()
    ids: list[str] = []
    for entry in data.get("models", []):
        for inst in entry.get("loaded_instances", []) or []:
            iid = inst.get("identifier") or inst.get("instance_id")
            if iid:
                ids.append(str(iid))
    return ids


async def load_model(cfg: SwapConfig, model_key: str, *, timeout: float = 120.0) -> str:
    """Загружает модель, возвращает её instance_id (нужен для
    последующего unload). Timeout щедрый — холодная загрузка
    26b-MoE может занять ~10 сек, в редких случаях больше."""
    async with _client(timeout) as client:
        resp = await client.post(
            f"{cfg.native_base}/models/load",
            json={"model": model_key},
        )
    if resp.status_code >= 400:
        raise SwapError(f"load {model_key} failed: {resp.status_code} {resp.text}")
    data = resp.json()
    iid = data.get("instance_id")
    if not iid:
        raise SwapError(f"load {model_key} returned no instance_id: {data}")
    return str(iid)


async def unload_model(cfg: SwapConfig, instance_id: str, *, timeout: float = 30.0) -> None:
    """Выгружает модель. instance_id обычно равен model key, но
    использовать API-ответ load()'а надёжнее."""
    async with _client(timeout) as client:
        resp = await client.post(
            f"{cfg.native_base}/models/unload",
            json={"instance_id": instance_id},
        )
    if resp.status_code >= 400:
        raise SwapError(f"unload {instance_id} failed: {resp.status_code} {resp.text}")


async def unload_all(cfg: SwapConfig) -> None:
    """Выгружает всё что сейчас загружено. Используется в начале
    swap-цикла чтобы освободить VRAM перед load(target)."""
    for iid in await loaded_instances(cfg):
        with contextlib.suppress(SwapError):
            # suppress: если параллельно ещё кто-то выгрузил —
            # 404 не должна валить цикл
            await unload_model(cfg, iid)


@contextlib.asynccontextmanager
async def swap_to(
    cfg: SwapConfig,
    target: str,
    *,
    fallback: str | None = None,
) -> AsyncIterator[str]:
    """Async-контекст: освобождает VRAM, грузит `target`, отдаёт
    его instance_id, потом возвращает на `fallback` если задан.

    Пример:
    ```python
    async with swap_to(cfg, "gemma-26b", fallback="qwen-14b"):
        result = await upstream_call(...)
    # сразу после yield: unload gemma, load qwen
    ```

    Гарантия: даже если внутри блока возникло исключение, мы
    **всегда** пытаемся вернуть fallback (если задан). Это
    важно — иначе следующий /go упрётся в «нет baseline в
    памяти» из-за неоткаченного состояния.
    """
    await unload_all(cfg)
    target_iid = await load_model(cfg, target)
    try:
        yield target_iid
    finally:
        with contextlib.suppress(SwapError):
            await unload_model(cfg, target_iid)
        if fallback is not None:
            with contextlib.suppress(SwapError):
                await load_model(cfg, fallback)


__all__ = [
    "SwapConfig",
    "SwapError",
    "load_model",
    "loaded_instances",
    "swap_to",
    "unload_all",
    "unload_model",
]
