from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx
import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator, model_validator

SYSTEM_CONFIG = Path.home() / ".config" / "code-scalpel" / "config.yaml"
PROJECT_CONFIG = Path(".code-scalpel") / "config.yaml"

_PROVIDER_BASE_URLS: dict[str, str] = {
    "lmstudio": "http://localhost:1234",
    "openai": "https://api.openai.com",
    "openrouter": "https://openrouter.ai/api",
}


class AgentConfig(BaseModel):
    llm_timeout: int = 120
    test_timeout: int = 60
    git_timeout: int = 10
    max_files: int = 3
    max_file_lines: int = 400
    max_debug_attempts: int = 2
    answer_reserve_tokens: int = 4000
    context_budget_warn: float = 0.70
    context_budget_critical: float = 0.90
    compact_threshold: float = 0.50


class ModeTemperatures(BaseModel):
    """Per-mode sampling temperature. ask/review default low (retrieval,
    analytical), plan moderate, code low-mid (single-shot patch generation),
    debug higher to give the retry diversity when the first patch fails."""

    ask: float = 0.1
    plan: float = 0.4
    code: float = 0.2
    review: float = 0.1
    debug: float = 0.5

    def for_mode(self, mode: str) -> float:
        # Unknown modes fall back to ask — safest default for surprising callers.
        return getattr(self, mode, self.ask)


class ModelProfile(BaseModel):
    provider: str
    model: str
    base_url: str | None = None
    context_tokens: int | None = None
    cost_per_1k: dict[str, float] | None = None
    # Per-mode temperature; the float shorthand applies one value to all modes.
    temperature: ModeTemperatures = Field(default_factory=ModeTemperatures)
    # Shared across all modes
    top_p: float = 0.9
    frequency_penalty: float | None = None
    seed: int | None = None

    @field_validator("temperature", mode="before")
    @classmethod
    def _temperature_scalar_shorthand(cls, v: Any) -> Any:
        if isinstance(v, int | float):
            value = float(v)
            return {"ask": value, "plan": value, "code": value, "review": value, "debug": value}
        return v

    def inference_kwargs(self, mode: str = "ask") -> dict[str, Any]:
        """Return inference params for a given mode. Temperature is per-mode;
        top_p / frequency_penalty / seed are shared."""
        result: dict[str, Any] = {
            "temperature": self.temperature.for_mode(mode),
            "top_p": self.top_p,
        }
        if self.frequency_penalty is not None:
            result["frequency_penalty"] = self.frequency_penalty
        if self.seed is not None:
            result["seed"] = self.seed
        return result

    def provider_base_url(self) -> str:
        if self.base_url:
            return self.base_url
        return _PROVIDER_BASE_URLS.get(self.provider, "http://localhost:1234")

    def api_key(self) -> str:
        env_map = {
            "lmstudio": "LMSTUDIO_API_KEY",
            "openai": "OPENAI_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
        }
        var = env_map.get(self.provider, "LLM_API_KEY")
        return os.environ.get(var, "lm-studio")


# Sentinels that trigger model auto-detect from the provider's /v1/models
# endpoint. "auto" is the new explicit form; "local-model" is kept for
# backwards compat with the previous default profile.
_MODEL_AUTO_SENTINELS = frozenset({"auto", "local-model", ""})


def _default_profiles() -> dict[str, ModelProfile]:
    return {
        "local": ModelProfile(
            provider="lmstudio",
            model="auto",
        )
    }


class AppConfig(BaseModel):
    language: str = "en"
    active_profile: str = "local"
    agent: AgentConfig = Field(default_factory=AgentConfig)
    profiles: dict[str, ModelProfile] = Field(default_factory=_default_profiles)

    @model_validator(mode="after")
    def _active_profile_exists(self) -> AppConfig:
        if self.profiles and self.active_profile not in self.profiles:
            raise ValueError(
                f"active_profile '{self.active_profile}' not found in profiles: "
                f"{list(self.profiles.keys())}"
            )
        return self

    @property
    def current_profile(self) -> ModelProfile:
        return self.profiles[self.active_profile]


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config() -> AppConfig:
    load_dotenv()
    data: dict[str, Any] = {}
    for path in [SYSTEM_CONFIG, PROJECT_CONFIG]:
        if path.exists():
            with open(path) as f:
                chunk: dict[str, Any] = yaml.safe_load(f) or {}
            data = _deep_merge(data, chunk)
    return AppConfig.model_validate(data)


_CTX_FIELDS = ("loaded_context_length", "context_length", "max_context_length", "context_window")


def _extract_ctx(model: dict[str, Any]) -> int | None:
    for f in _CTX_FIELDS:
        v = model.get(f)
        if v:
            return int(v)
    return None


async def _fetch_models(profile: ModelProfile) -> list[dict[str, Any]]:
    """Fetch the provider's model list. Tries LM Studio's richer REST API
    first, then OpenAI-compatible /v1/models. Returns [] on any failure."""
    base = profile.provider_base_url()
    urls = [f"{base}/api/v0/models", f"{base}/v1/models"]
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            for url in urls:
                try:
                    resp = await client.get(url)
                    resp.raise_for_status()
                except Exception:
                    continue
                data = resp.json().get("data", [])
                if isinstance(data, list) and data:
                    return [m for m in data if isinstance(m, dict)]
    except Exception:
        pass
    return []


async def autodetect_context_tokens(profile: ModelProfile) -> int | None:
    """Detect context window. Matches profile.model first; if no match, falls
    back to the first model in the list (LM Studio typically serves one)."""
    models = await _fetch_models(profile)
    first_ctx: int | None = None
    for m in models:
        ctx = _extract_ctx(m)
        if ctx is not None:
            if first_ctx is None:
                first_ctx = ctx
            if m.get("id") == profile.model:
                return ctx
    return first_ctx


async def autodetect_model_name(profile: ModelProfile) -> str | None:
    """Pick the model id served by the provider. LM Studio (and most local
    runtimes) serve a single model at a time — we return its first id."""
    models = await _fetch_models(profile)
    for m in models:
        model_id = m.get("id")
        if isinstance(model_id, str) and model_id:
            return model_id
    return None


async def resolve_model_name(profile: ModelProfile) -> str:
    """Return the model id the adapter should pass to the provider.

    Manual override wins: if the profile names a specific model, it's used
    verbatim — provider must serve that exact id. The "auto" sentinel (and
    the legacy "local-model" placeholder) trigger detection from the
    provider's /v1/models endpoint. If detection fails, we keep the sentinel
    so LM Studio's "use the loaded model regardless of name" behaviour still
    works as a last resort.
    """
    if profile.model and profile.model not in _MODEL_AUTO_SENTINELS:
        return profile.model
    detected = await autodetect_model_name(profile)
    return detected if detected else profile.model


async def resolve_context_tokens(profile: ModelProfile) -> int:
    if profile.context_tokens is not None:
        return profile.context_tokens
    detected = await autodetect_context_tokens(profile)
    if detected is not None:
        return detected
    raise ValueError(
        f"Cannot determine context_tokens for model '{profile.model}'. "
        "Set context_tokens in your config profile."
    )
