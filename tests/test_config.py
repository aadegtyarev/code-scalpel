from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from code_scalpel.config import (
    AppConfig,
    ModelProfile,
    ModeTemperatures,
    _deep_merge,
    _extract_thinking_from_api_model,
    autodetect_context_tokens,
    autodetect_model_name,
    autodetect_supports_thinking,
    detect_supports_thinking,
    load_config,
    resolve_context_tokens,
    resolve_model_name,
)


def _mock_httpx_with_models(models: list[dict[str, object]]) -> AsyncMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"data": models}
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.get = AsyncMock(return_value=resp)
    return client


def test_default_config() -> None:
    config = AppConfig.model_validate({})
    assert config.language == "en"
    assert config.agent.max_files == 3
    assert config.agent.context_budget_warn == 0.70
    assert config.agent.answer_reserve_tokens == 4000


def test_deep_merge_nested() -> None:
    base = {"a": 1, "b": {"c": 2, "d": 3}}
    override = {"b": {"c": 99}, "e": 5}
    result = _deep_merge(base, override)
    assert result == {"a": 1, "b": {"c": 99, "d": 3}, "e": 5}


def test_deep_merge_does_not_mutate() -> None:
    base = {"x": {"y": 1}}
    override = {"x": {"z": 2}}
    _deep_merge(base, override)
    assert base == {"x": {"y": 1}}


def test_invalid_active_profile_raises() -> None:
    with pytest.raises(ValueError, match="active_profile 'missing'"):
        AppConfig.model_validate(
            {
                "active_profile": "missing",
                "profiles": {
                    "local": {"provider": "lmstudio", "model": "qwen"},
                },
            }
        )


def test_current_profile() -> None:
    config = AppConfig.model_validate(
        {
            "active_profile": "local",
            "profiles": {
                "local": {
                    "provider": "lmstudio",
                    "model": "qwen2.5-coder-14b-instruct",
                },
            },
        }
    )
    assert config.current_profile.model == "qwen2.5-coder-14b-instruct"


def test_load_config_merges_system_and_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    system_cfg = tmp_path / "system.yaml"
    system_cfg.write_text(
        yaml.dump(
            {
                "active_profile": "local",
                "agent": {"max_files": 3},
                "profiles": {
                    "local": {
                        "provider": "lmstudio",
                        "model": "qwen2.5-coder-14b-instruct",
                    },
                },
            }
        )
    )
    project_cfg = tmp_path / "project.yaml"
    project_cfg.write_text(yaml.dump({"agent": {"max_files": 5}}))

    monkeypatch.setattr("code_scalpel.config.SYSTEM_CONFIG", system_cfg)
    monkeypatch.setattr("code_scalpel.config.PROJECT_CONFIG", project_cfg)

    config = load_config()
    assert config.agent.max_files == 5
    assert config.active_profile == "local"
    assert config.agent.max_debug_attempts == 2  # default preserved


def test_load_config_no_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("code_scalpel.config.SYSTEM_CONFIG", tmp_path / "nope.yaml")
    monkeypatch.setattr("code_scalpel.config.PROJECT_CONFIG", tmp_path / "nope2.yaml")
    config = load_config()
    assert config.language == "en"


def test_inference_kwargs_defaults_to_ask_temperature() -> None:
    profile = ModelProfile(provider="lmstudio", model="qwen")
    kwargs = profile.inference_kwargs()
    # ask mode is the default; top_p ships always.
    # Default `ask` temperature was bumped from 0.1 → 0.7 (closer to
    # the model's own default of ~0.8). At 0.1 the weak local model
    # consistently bounced query-tasks with "Извините не могу найти"
    # instead of calling project_map; higher temperature breaks the
    # deterministic-refusal pattern.
    assert kwargs == {"temperature": 0.7, "top_p": 0.9}


def test_inference_kwargs_per_mode_temperature() -> None:
    profile = ModelProfile(provider="lmstudio", model="qwen")
    # New defaults — closer to model-native ~0.8. Probe confirmed
    # the deterministic-refusal pattern at 0.1 disappears at 0.7.
    assert profile.inference_kwargs("ask")["temperature"] == 0.7
    assert profile.inference_kwargs("plan")["temperature"] == 0.6
    assert profile.inference_kwargs("code")["temperature"] == 0.3
    assert profile.inference_kwargs("review")["temperature"] == 0.3
    assert profile.inference_kwargs("debug")["temperature"] == 0.7


def test_inference_kwargs_unknown_mode_falls_back_to_ask() -> None:
    profile = ModelProfile(provider="lmstudio", model="qwen")
    assert profile.inference_kwargs("nonsense")["temperature"] == 0.7


def test_inference_kwargs_top_p_overridable() -> None:
    profile = ModelProfile(provider="lmstudio", model="qwen", top_p=0.5)
    assert profile.inference_kwargs()["top_p"] == 0.5


def test_inference_kwargs_optional_fields_only_when_set() -> None:
    profile = ModelProfile(provider="lmstudio", model="qwen")
    kwargs = profile.inference_kwargs()
    assert "frequency_penalty" not in kwargs
    assert "seed" not in kwargs

    profile2 = ModelProfile(provider="lmstudio", model="qwen", frequency_penalty=0.3, seed=42)
    kwargs2 = profile2.inference_kwargs()
    assert kwargs2["frequency_penalty"] == 0.3
    assert kwargs2["seed"] == 42


def test_temperature_scalar_shorthand_applies_to_all_modes() -> None:
    profile = ModelProfile(provider="lmstudio", model="qwen", temperature=0.3)
    for mode in ("ask", "plan", "code", "review", "debug"):
        assert profile.inference_kwargs(mode)["temperature"] == 0.3


def test_temperature_explicit_per_mode_via_dict() -> None:
    profile = ModelProfile(
        provider="lmstudio",
        model="qwen",
        temperature=ModeTemperatures(ask=0.0, code=0.5),
    )
    assert profile.inference_kwargs("ask")["temperature"] == 0.0
    assert profile.inference_kwargs("code")["temperature"] == 0.5
    # Unspecified modes keep their defaults.
    assert profile.inference_kwargs("debug")["temperature"] == 0.7  # default
    assert profile.inference_kwargs("plan")["temperature"] == 0.6  # default


def test_provider_base_url_default() -> None:
    profile = ModelProfile(provider="lmstudio", model="qwen")
    assert profile.provider_base_url() == "http://localhost:1234"


def test_provider_base_url_override() -> None:
    profile = ModelProfile(provider="lmstudio", model="qwen", base_url="http://custom:5678")
    assert profile.provider_base_url() == "http://custom:5678"


@pytest.mark.asyncio
async def test_autodetect_context_tokens_found() -> None:
    profile = ModelProfile(provider="lmstudio", model="qwen2.5-coder-14b-instruct")

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "data": [{"id": "qwen2.5-coder-14b-instruct", "context_length": 32768}]
    }

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch("code_scalpel.config.httpx.AsyncClient", return_value=mock_client):
        result = await autodetect_context_tokens(profile)

    assert result == 32768


@pytest.mark.asyncio
async def test_autodetect_prefers_loaded_context_length() -> None:
    """LM Studio's /api/v0/models exposes loaded_context_length — use it over max."""
    profile = ModelProfile(provider="lmstudio", model="qwen/qwen2.5-coder-14b")

    api_v0 = MagicMock()
    api_v0.raise_for_status = MagicMock()
    api_v0.json.return_value = {
        "data": [
            {
                "id": "qwen/qwen2.5-coder-14b",
                "max_context_length": 32768,
                "loaded_context_length": 16384,
            }
        ]
    }

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=api_v0)

    with patch("code_scalpel.config.httpx.AsyncClient", return_value=mock_client):
        result = await autodetect_context_tokens(profile)

    assert result == 16384


@pytest.mark.asyncio
async def test_autodetect_falls_back_to_first_model() -> None:
    """When no model id matches, use the first model's context length."""
    profile = ModelProfile(provider="lmstudio", model="something-not-loaded")

    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "data": [
            {"id": "actual-model", "loaded_context_length": 8192},
            {"id": "other", "max_context_length": 4096},
        ]
    }

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=resp)

    with patch("code_scalpel.config.httpx.AsyncClient", return_value=mock_client):
        result = await autodetect_context_tokens(profile)

    assert result == 8192


@pytest.mark.asyncio
async def test_autodetect_falls_back_to_v1_when_v0_missing() -> None:
    """If /api/v0/models 404s, try /v1/models (OpenAI compatible)."""
    profile = ModelProfile(provider="lmstudio", model="x")

    v0_resp = MagicMock()
    v0_resp.raise_for_status = MagicMock(side_effect=Exception("404"))
    v1_resp = MagicMock()
    v1_resp.raise_for_status = MagicMock()
    v1_resp.json.return_value = {"data": [{"id": "x", "context_length": 4096}]}

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(side_effect=[v0_resp, v1_resp])

    with patch("code_scalpel.config.httpx.AsyncClient", return_value=mock_client):
        result = await autodetect_context_tokens(profile)

    assert result == 4096


@pytest.mark.asyncio
async def test_autodetect_context_tokens_network_error() -> None:
    profile = ModelProfile(provider="lmstudio", model="qwen")

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(side_effect=Exception("connection refused"))

    with patch("code_scalpel.config.httpx.AsyncClient", return_value=mock_client):
        result = await autodetect_context_tokens(profile)

    assert result is None


@pytest.mark.asyncio
async def test_resolve_uses_config_value() -> None:
    profile = ModelProfile(provider="lmstudio", model="qwen", context_tokens=24000)
    result = await resolve_context_tokens(profile)
    assert result == 24000


@pytest.mark.asyncio
async def test_resolve_raises_when_no_source() -> None:
    profile = ModelProfile(provider="lmstudio", model="qwen")
    with (
        patch("code_scalpel.config.autodetect_context_tokens", return_value=None),
        pytest.raises(ValueError, match="context_tokens"),
    ):
        await resolve_context_tokens(profile)


# ── model name detection / resolution ────────────────────────────────────────


@pytest.mark.asyncio
async def test_autodetect_model_name_returns_first_id() -> None:
    profile = ModelProfile(provider="lmstudio", model="auto")
    client = _mock_httpx_with_models(
        [{"id": "qwen2.5-coder-14b-instruct", "context_length": 32768}]
    )
    with patch("code_scalpel.config.httpx.AsyncClient", return_value=client):
        result = await autodetect_model_name(profile)
    assert result == "qwen2.5-coder-14b-instruct"


@pytest.mark.asyncio
async def test_autodetect_model_name_skips_empty_ids() -> None:
    profile = ModelProfile(provider="lmstudio", model="auto")
    client = _mock_httpx_with_models([{"id": ""}, {"id": None}, {"id": "real-model"}])
    with patch("code_scalpel.config.httpx.AsyncClient", return_value=client):
        result = await autodetect_model_name(profile)
    assert result == "real-model"


@pytest.mark.asyncio
async def test_autodetect_model_name_returns_none_on_empty_list() -> None:
    profile = ModelProfile(provider="lmstudio", model="auto")
    client = _mock_httpx_with_models([])
    with patch("code_scalpel.config.httpx.AsyncClient", return_value=client):
        result = await autodetect_model_name(profile)
    assert result is None


@pytest.mark.asyncio
async def test_resolve_model_name_manual_override_wins() -> None:
    """Explicit model id in config is passed through untouched — no /v1/models hit."""
    profile = ModelProfile(provider="lmstudio", model="qwen2.5-coder-14b")
    with patch("code_scalpel.config.autodetect_model_name", new=AsyncMock()) as detected:
        result = await resolve_model_name(profile)
    assert result == "qwen2.5-coder-14b"
    detected.assert_not_called()


@pytest.mark.asyncio
async def test_resolve_model_name_auto_sentinel_triggers_detection() -> None:
    profile = ModelProfile(provider="lmstudio", model="auto")
    with patch(
        "code_scalpel.config.autodetect_model_name",
        new=AsyncMock(return_value="qwen-detected"),
    ):
        result = await resolve_model_name(profile)
    assert result == "qwen-detected"


@pytest.mark.asyncio
async def test_resolve_model_name_legacy_local_model_sentinel() -> None:
    """Old configs/defaults shipped `model: local-model`. Treat it as auto-detect
    so they keep working without manual edits."""
    profile = ModelProfile(provider="lmstudio", model="local-model")
    with patch(
        "code_scalpel.config.autodetect_model_name",
        new=AsyncMock(return_value="qwen-detected"),
    ):
        result = await resolve_model_name(profile)
    assert result == "qwen-detected"


@pytest.mark.asyncio
async def test_resolve_model_name_falls_back_to_sentinel_on_detect_fail() -> None:
    """When detection returns nothing (server down, empty list), keep the
    placeholder — LM Studio's 'use whatever is loaded' behavior is the safety
    net, and we'd rather show 'auto' than crash."""
    profile = ModelProfile(provider="lmstudio", model="auto")
    with patch("code_scalpel.config.autodetect_model_name", new=AsyncMock(return_value=None)):
        result = await resolve_model_name(profile)
    assert result == "auto"


def test_default_profile_uses_auto_sentinel() -> None:
    """Out-of-the-box default profile should self-discover its model."""
    config = AppConfig.model_validate({})
    assert config.current_profile.model == "auto"


# ── detect_supports_thinking (name-pattern) ──────────────────────────────────


@pytest.mark.parametrize(
    "model_name",
    ["o1-mini", "o1-preview", "o3", "o3-mini", "qwq-32b", "deepseek-r1-7b", "claude-3-7-sonnet"],
)
def test_detect_supports_thinking_known_patterns(model_name: str) -> None:
    assert detect_supports_thinking(model_name) is True


@pytest.mark.parametrize(
    "model_name",
    ["qwen2.5-coder-14b", "llama-3-8b", "mistral-7b", "gpt-4o", "claude-3-5-sonnet"],
)
def test_detect_supports_thinking_unknown_patterns(model_name: str) -> None:
    assert detect_supports_thinking(model_name) is False


def test_detect_supports_thinking_case_insensitive() -> None:
    assert detect_supports_thinking("OpenAI/O3-Mini") is True
    assert detect_supports_thinking("QWQ-32B-Preview") is True


# ── _extract_thinking_from_api_model ─────────────────────────────────────────


def test_extract_openrouter_supported_parameters_reasoning_effort() -> None:
    model = {"id": "openai/o3-mini", "supported_parameters": ["max_tokens", "reasoning_effort"]}
    assert _extract_thinking_from_api_model(model) is True


def test_extract_openrouter_supported_parameters_reasoning() -> None:
    model = {"id": "anthropic/claude-3-7", "supported_parameters": ["temperature", "reasoning"]}
    assert _extract_thinking_from_api_model(model) is True


def test_extract_openrouter_no_reasoning_in_supported_parameters() -> None:
    """OpenRouter lists all params → absence means not supported."""
    model = {"id": "mistral-7b", "supported_parameters": ["temperature", "top_p", "max_tokens"]}
    assert _extract_thinking_from_api_model(model) is False


def test_extract_lmstudio_capabilities_list_with_reasoning() -> None:
    model = {"id": "qwq-32b", "capabilities": ["chat", "tools", "reasoning"]}
    assert _extract_thinking_from_api_model(model) is True


def test_extract_lmstudio_capabilities_list_without_reasoning_returns_none() -> None:
    """LM Studio omits caps it doesn't advertise — no reasoning doesn't mean False."""
    model = {"id": "qwen-14b", "capabilities": ["chat", "tools"]}
    assert _extract_thinking_from_api_model(model) is None


def test_extract_capabilities_dict_reasoning_true() -> None:
    model = {"id": "some-model", "capabilities": {"reasoning": True, "vision": False}}
    assert _extract_thinking_from_api_model(model) is True


def test_extract_capabilities_dict_reasoning_false() -> None:
    model = {"id": "some-model", "capabilities": {"reasoning": False}}
    assert _extract_thinking_from_api_model(model) is False


def test_extract_no_known_fields_returns_none() -> None:
    model = {"id": "mystery-model", "description": "..."}
    assert _extract_thinking_from_api_model(model) is None


# ── autodetect_supports_thinking ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_autodetect_thinking_from_api_wins_over_name_pattern() -> None:
    """API says False for a model whose name matches a thinking pattern —
    API must win (explicit beats heuristic)."""
    profile = ModelProfile(provider="openrouter", model="o3-mini")
    api_models = [{"id": "o3-mini", "supported_parameters": ["temperature"]}]
    with patch("code_scalpel.config._fetch_models", new=AsyncMock(return_value=api_models)):
        result = await autodetect_supports_thinking(profile, "o3-mini")
    assert result is False


@pytest.mark.asyncio
async def test_autodetect_thinking_api_true() -> None:
    profile = ModelProfile(provider="openrouter", model="o3-mini")
    api_models = [{"id": "o3-mini", "supported_parameters": ["reasoning_effort"]}]
    with patch("code_scalpel.config._fetch_models", new=AsyncMock(return_value=api_models)):
        result = await autodetect_supports_thinking(profile, "o3-mini")
    assert result is True


@pytest.mark.asyncio
async def test_autodetect_thinking_falls_back_to_name_pattern_when_api_inconclusive() -> None:
    """LM Studio returns capabilities list without 'reasoning' → None → name-pattern."""
    profile = ModelProfile(provider="lmstudio", model="qwq-32b")
    api_models = [{"id": "qwq-32b", "capabilities": ["chat", "tools"]}]
    with patch("code_scalpel.config._fetch_models", new=AsyncMock(return_value=api_models)):
        result = await autodetect_supports_thinking(profile, "qwq-32b")
    # Name pattern "qwq" matches → True
    assert result is True


@pytest.mark.asyncio
async def test_autodetect_thinking_falls_back_when_no_api_data() -> None:
    """Empty model list → name-pattern only."""
    profile = ModelProfile(provider="lmstudio", model="qwq-32b")
    with patch("code_scalpel.config._fetch_models", new=AsyncMock(return_value=[])):
        result = await autodetect_supports_thinking(profile, "qwq-32b")
    assert result is True


@pytest.mark.asyncio
async def test_autodetect_thinking_uses_first_model_when_no_id_match() -> None:
    """Server serves one model under a different id — fall back to first entry."""
    profile = ModelProfile(provider="lmstudio", model="auto")
    api_models = [{"id": "loaded-model", "supported_parameters": ["reasoning_effort"]}]
    with patch("code_scalpel.config._fetch_models", new=AsyncMock(return_value=api_models)):
        result = await autodetect_supports_thinking(profile, "resolved-name")
    assert result is True


# ── inference_kwargs with thinking_effort ─────────────────────────────────────


def test_inference_kwargs_thinking_effort_off_no_reasoning_param() -> None:
    profile = ModelProfile(provider="lmstudio", model="qwq-32b", supports_thinking=True)
    kwargs = profile.inference_kwargs("ask", thinking_effort="off")
    assert "reasoning_effort" not in kwargs


def test_inference_kwargs_thinking_effort_adds_reasoning_effort() -> None:
    profile = ModelProfile(provider="openrouter", model="o3-mini", supports_thinking=True)
    for effort in ("low", "medium", "high"):
        kwargs = profile.inference_kwargs("ask", thinking_effort=effort)
        assert kwargs["reasoning_effort"] == effort


def test_inference_kwargs_thinking_effort_ignored_when_not_supported() -> None:
    profile = ModelProfile(provider="lmstudio", model="qwen-14b", supports_thinking=False)
    kwargs = profile.inference_kwargs("ask", thinking_effort="high")
    assert "reasoning_effort" not in kwargs


def test_inference_kwargs_thinking_auto_detect_via_name_pattern() -> None:
    """supports_thinking=None → auto-detect from model name in inference_kwargs."""
    thinking_profile = ModelProfile(provider="lmstudio", model="qwq-32b")
    assert "reasoning_effort" in thinking_profile.inference_kwargs("ask", thinking_effort="low")

    plain_profile = ModelProfile(provider="lmstudio", model="qwen2.5-coder-14b")
    assert "reasoning_effort" not in plain_profile.inference_kwargs("ask", thinking_effort="low")
