from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx
import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, model_validator

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


class ModelProfile(BaseModel):
    provider: str
    model: str
    base_url: str | None = None
    context_tokens: int | None = None
    cost_per_1k: dict[str, float] | None = None
    # LLM inference parameters — passed directly to chat/stream calls
    temperature: float | None = None
    top_p: float | None = None
    frequency_penalty: float | None = None
    seed: int | None = None

    def inference_kwargs(self) -> dict[str, float | int]:
        """Return only explicitly set inference params for passing to LLM calls."""
        result: dict[str, float | int] = {}
        if self.temperature is not None:
            result["temperature"] = self.temperature
        if self.top_p is not None:
            result["top_p"] = self.top_p
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


def _default_profiles() -> dict[str, ModelProfile]:
    return {
        "local": ModelProfile(
            provider="lmstudio",
            model="local-model",
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


async def autodetect_context_tokens(profile: ModelProfile) -> int | None:
    url = f"{profile.provider_base_url()}/v1/models"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            for m in resp.json().get("data", []):
                if m.get("id") == profile.model:
                    length: int | None = m.get("context_length")
                    return length
    except Exception:
        pass
    return None


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
