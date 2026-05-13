"""LM Studio swap orchestration — load/unload + swap_to context.

Реальную LM Studio не дёргаем: всё через httpx.MockTransport. Цель
— зафиксировать REST contract (что мы шлём и куда) и поведение
swap_to при ошибках (fallback всегда восстанавливается)."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from code_scalpel.llm.lmstudio_swap import (
    SwapConfig,
    SwapError,
    load_model,
    loaded_instances,
    set_test_transport,
    swap_to,
    unload_all,
    unload_model,
)


@pytest.fixture(autouse=True)
def _reset_transport() -> object:
    """После каждого теста снимаем тестовый transport, чтобы он
    не утёк в другие модули."""
    yield None
    set_test_transport(None)


CFG = SwapConfig(native_base="http://localhost:1234/api/v1")


def _mock_client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_swap_config_from_openai_base() -> None:
    cfg = SwapConfig.from_openai_base("http://localhost:1234/v1")
    assert cfg.native_base == "http://localhost:1234/api/v1"

    cfg2 = SwapConfig.from_openai_base("https://lms.example.com/v1")
    assert cfg2.native_base == "https://lms.example.com/api/v1"


@pytest.mark.asyncio
async def test_load_model_returns_instance_id(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.content.decode()
        return httpx.Response(
            200,
            json={
                "instance_id": "qwen/qwen2.5-coder-14b",
                "status": "loaded",
                "load_time_seconds": 5.2,
            },
        )

    set_test_transport(httpx.MockTransport(handler))
    iid = await load_model(CFG, "qwen/qwen2.5-coder-14b")
    assert iid == "qwen/qwen2.5-coder-14b"
    assert captured["url"] == "http://localhost:1234/api/v1/models/load"
    assert '"model"' in str(captured["body"])
    assert "qwen/qwen2.5-coder-14b" in str(captured["body"])


@pytest.mark.asyncio
async def test_load_model_raises_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"message": "out of VRAM"}})

    set_test_transport(httpx.MockTransport(handler))
    with pytest.raises(SwapError, match="load.*failed"):
        await load_model(CFG, "huge-model")


@pytest.mark.asyncio
async def test_load_model_raises_if_no_instance_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """Защита от изменения REST-схемы — если LM Studio вернёт
    200 без instance_id, мы это ловим, а не молча возвращаем
    пустую строку."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "loaded"})  # нет instance_id

    set_test_transport(httpx.MockTransport(handler))
    with pytest.raises(SwapError, match="no instance_id"):
        await load_model(CFG, "foo")


@pytest.mark.asyncio
async def test_unload_model_posts_instance_id(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.content.decode()
        return httpx.Response(200, json={"instance_id": "foo"})

    set_test_transport(httpx.MockTransport(handler))
    await unload_model(CFG, "foo")
    assert "/models/unload" in captured["url"]
    assert '"instance_id"' in captured["body"]
    assert '"foo"' in captured["body"]


@pytest.mark.asyncio
async def test_loaded_instances_parses_models(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "models": [
                    {
                        "key": "qwen/qwen2.5-coder-14b",
                        "loaded_instances": [{"identifier": "qwen/qwen2.5-coder-14b"}],
                    },
                    {"key": "gemma-26b", "loaded_instances": []},
                    {"key": "other", "loaded_instances": [{"identifier": "other"}]},
                ]
            },
        )

    set_test_transport(httpx.MockTransport(handler))
    ids = await loaded_instances(CFG)
    assert ids == ["qwen/qwen2.5-coder-14b", "other"]


@pytest.mark.asyncio
async def test_unload_all_unloads_each(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(
                200,
                json={
                    "models": [
                        {"loaded_instances": [{"identifier": "a"}, {"identifier": "b"}]},
                    ]
                },
            )
        body = request.content.decode()
        calls.append((str(request.url.path), body))
        return httpx.Response(200, json={})

    set_test_transport(httpx.MockTransport(handler))
    await unload_all(CFG)
    # Оба instance'а отписаны
    unload_calls = [b for path, b in calls if path.endswith("/unload")]
    assert any('"a"' in b for b in unload_calls)
    assert any('"b"' in b for b in unload_calls)


@pytest.mark.asyncio
async def test_swap_to_normal_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    """Happy path: unload existing → load target → yield → unload
    target → load fallback."""
    operations: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/models") and request.method == "GET":
            return httpx.Response(
                200,
                json={"models": [{"loaded_instances": [{"identifier": "qwen-14b"}]}]},
            )
        body = request.content.decode()
        operations.append((path, body))
        if path.endswith("/load"):
            return httpx.Response(
                200,
                json={
                    "instance_id": "gemma-26b" if "gemma" in body else "qwen-14b",
                    "status": "loaded",
                },
            )
        return httpx.Response(200, json={"instance_id": "x"})

    set_test_transport(httpx.MockTransport(handler))
    async with swap_to(CFG, "gemma-26b", fallback="qwen-14b") as target_iid:
        assert target_iid == "gemma-26b"
        operations.append(("/yield", ""))

    paths = [p for p, _ in operations]
    # ожидаем порядок: unload(qwen), load(gemma), yield, unload(gemma), load(qwen)
    assert paths.index("/api/v1/models/unload") < paths.index("/api/v1/models/load")
    assert (
        paths.index("/yield")
        < paths[paths.index("/yield") + 1 :].index("/api/v1/models/unload")
        + paths.index("/yield")
        + 1
    )
    # Финальный load должен быть на qwen-14b
    last_load_body = next(b for p, b in reversed(operations) if p.endswith("/load"))
    assert "qwen-14b" in last_load_body


@pytest.mark.asyncio
async def test_swap_to_restores_fallback_on_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """Если внутри swap_to падает исключение — всё равно
    разгружаем target и грузим fallback. Критично: иначе следующий
    /go упрётся в пустой VRAM или чужую модель."""
    operations: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/models") and request.method == "GET":
            return httpx.Response(200, json={"models": []})
        body = request.content.decode()
        operations.append((path, body))
        return httpx.Response(
            200, json={"instance_id": "gemma" if "gemma" in body else "qwen", "status": "loaded"}
        )

    set_test_transport(httpx.MockTransport(handler))
    with pytest.raises(RuntimeError, match="kaboom"):
        async with swap_to(CFG, "gemma", fallback="qwen"):
            raise RuntimeError("kaboom")

    # Fallback всё равно загрузился
    last_load_body = next(b for p, b in reversed(operations) if p.endswith("/load"))
    assert "qwen" in last_load_body


@pytest.mark.asyncio
async def test_swap_to_works_without_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """fallback=None — после блока target выгружается, baseline
    не восстанавливается. Полезно для CLI «выгрузи и забудь»."""
    operations: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/models") and request.method == "GET":
            return httpx.Response(200, json={"models": []})
        body = request.content.decode()
        operations.append((path, body))
        return httpx.Response(200, json={"instance_id": "gemma", "status": "loaded"})

    set_test_transport(httpx.MockTransport(handler))
    async with swap_to(CFG, "gemma", fallback=None):
        pass

    load_count = sum(1 for p, _ in operations if p.endswith("/load"))
    assert load_count == 1  # только target, без re-load fallback
