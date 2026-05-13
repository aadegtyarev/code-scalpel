from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

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
    # Opt-in: when on, code/run modes auto-run tests after a patch applies and
    # ask the model to fix on failure, up to max_debug_attempts retries.
    # Off by default — the TUI flips this once the iterative loop is wired in.
    iterative_patch_loop: bool = False
    # Opt-in: when on, code_with_retry rejects a successful patch that touched
    # production code (any .py file outside tests/) but didn't add or modify
    # a test. The model is asked to produce a follow-up adding a test for the
    # change, counted against `max_debug_attempts`. Plain patch-only requests
    # (where the user explicitly doesn't want tests) opt out by leaving the
    # flag off — default off so a casual `/code` task isn't gated on tests.
    require_tests: bool = False
    # Opt-out: when on, the agent rejects a reply that emits a SEARCH/REPLACE
    # block (or fenced python body) for a file it never called read_file on —
    # in this turn or any previous one. The model is sent a follow-up asking
    # it to read first, then re-emit. Default ON: helps weak local models
    # avoid fabricating from training-data shape; capable models don't lose
    # anything because they'd have read the file anyway.
    enforce_read_before_show: bool = True
    # Opt-out: when on, the agent walks history at the end of each turn
    # and replaces long, stale tool-role messages with a one-line
    # marker that keeps the round-trip shape but drops the payload.
    # Default ON — weak local models with a 16-32k context budget
    # benefit most. The two knobs below decide what "stale" and "long"
    # mean: a tool message is rewritten only if BOTH conditions hold.
    compress_tool_results: bool = True
    compress_tool_results_after_turns: int = 3
    compress_tool_results_min_chars: int = 800
    # Opt-in: when on AND `compress_tool_results` on, the compression
    # pass asks the model for a one-line summary of each stale tool
    # output and uses it as the marker hint, instead of the
    # deterministic "first non-empty line". Useful when tool outputs
    # start with generic headers ("OK", "matches:", table titles) — an
    # LLM summary distills the actual result. Costs an extra short
    # round-trip per compressed message; default off.
    compress_with_llm: bool = False
    answer_reserve_tokens: int = 4000
    context_budget_warn: float = 0.70
    context_budget_critical: float = 0.90
    compact_threshold: float = 0.50
    # UI locale: "en", "ru", or `None` to autodetect from `LC_*`/`LANG`.
    # Only the TUI surface is affected — prompts the model sees stay
    # English regardless (weak local models perform better on English).
    ui_locale: str | None = None
    # How much the user trusts the model to act without per-step
    # confirmation. One knob covers shell_exec policy AND patch-apply
    # auto-acceptance, because both questions are "trust the model to
    # do X autonomously?". See code_scalpel/policy.py for the levels.
    #   skeptic  — manual confirm on shell_exec and patches (default).
    #   optimist — auto-run within a hard-block list (no rm -rf /,
    #              no sudo, no pipe-to-shell, …); patches auto-apply.
    #   yolo     — autopilot, no filters. Sandbox VMs only.
    trust: Literal["skeptic", "optimist", "yolo"] = "skeptic"
    # Hard cap on each shell_exec call. Independent of trust level —
    # a hung command must not block the agent indefinitely.
    shell_exec_timeout: int = 30
    # Filesystem sandbox for shell_exec. `auto` uses bwrap if installed,
    # falls back to bare subprocess otherwise. `on` requires bwrap (refuses
    # to run shell_exec without it). `off` disables sandboxing entirely.
    # Sandbox confines the command to the project directory; /home, /etc,
    # and other host paths are not visible (network IS shared, for pip /
    # LLM calls). See `code_scalpel/tools/sandbox.py` for layout details.
    sandbox: Literal["auto", "on", "off"] = "auto"
    # Plan-runner git integration. When on: run_plan auto-inits a git
    # repo (with starter .gitignore) before the first task, and validates
    # that HEAD advanced after each task (model is required to commit
    # via the code-mode checklist). Off keeps the loop hermetic, which
    # tests rely on (mocks don't expect shell calls from the runner
    # itself). Off in tests, on in production.
    auto_git: bool = True
    # Auto-annotate the plan with per-task `Skills:` lines at /go time
    # when none are present. Fires ONE extra LLM call before the loop
    # starts. Off in tests so the mocked LLM queue stays predictable.
    auto_annotate_plan: bool = True
    # Inference thinking effort — passed to providers that support it
    # (o1/o3, deepseek-r1, qwq). Ignored when ModelProfile.supports_thinking
    # is False or None (auto-detected as unsupported). Toggled via Ctrl+K.
    thinking_effort: Literal["off", "low", "medium", "high"] = "off"
    # Per-step review: after every successful task in /go, fire an
    # independent reviewer turn (same model, different system prompt,
    # higher temperature, read-only tools). The reviewer surfaces risks
    # as a chat card; no auto-fix yet — that's a follow-up. Off by
    # default so legacy /go behaviour is preserved; enable when you
    # want the v0.8 «narrow passes» reliability bet active.
    per_step_review: bool = False
    # Sampling temperature for the reviewer turn. Higher than builder
    # (0.3 in `code` mode) so the reviewer generates diverse hypotheses
    # about what could break, rather than locking in on the first read.
    review_temperature: float = 0.5
    # Test-sanity narrow pass: after every successful task in /go that
    # touched a test file, fire an independent judge — does the test
    # actually exercise behaviour, or would it pass against a stub?
    # Trivial → failed task, retry with explicit guidance. Off by
    # default; the v0.8 reliability bet only ships active when the
    # user opts in.
    test_sanity_pass: bool = False
    # AST-based empty-test detector. Static pair of test_sanity_pass —
    # finds tests whose body is only `pass`, `assert <literal>`, or has
    # no Call expression at all. Cheaper than the LLM judge, deterministic,
    # catches the obvious shape; the LLM still catches the
    # `assert x is not None` cases that look meaningful structurally.
    # Off by default to preserve legacy /go.
    empty_test_detect: bool = False


class ModeTemperatures(BaseModel):
    """Per-mode sampling temperature.

    `ask` was 0.1 — too deterministic for a weak local model. Probe
    showed it bouncing query-tasks with "Извините, не могу найти X"
    instead of calling `project_map()`. At higher temperature the
    same model picks exploration over the "I don't know" reflex.
    Bumped to 0.3 — still well under "creative" but enough to break
    the consistent-refusal pattern.

    plan stays moderate (creative breakdown). code stays low-mid
    (single-shot patch precision). debug high (retry diversity).
    """

    ask: float = 0.7
    plan: float = 0.6
    code: float = 0.3
    review: float = 0.3
    debug: float = 0.7

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
    # Whether the model supports thinking/reasoning params (reasoning_effort).
    # None = auto-detect from model name; True/False = manual override in config.
    supports_thinking: bool | None = None

    @field_validator("temperature", mode="before")
    @classmethod
    def _temperature_scalar_shorthand(cls, v: Any) -> Any:
        if isinstance(v, int | float):
            value = float(v)
            return {"ask": value, "plan": value, "code": value, "review": value, "debug": value}
        return v

    def inference_kwargs(self, mode: str = "ask", thinking_effort: str = "off") -> dict[str, Any]:
        """Return inference params for a given mode. Temperature is per-mode;
        top_p / frequency_penalty / seed are shared. When thinking_effort is
        not "off" and the profile supports thinking, reasoning_effort is added."""
        result: dict[str, Any] = {
            "temperature": self.temperature.for_mode(mode),
            "top_p": self.top_p,
        }
        if self.frequency_penalty is not None:
            result["frequency_penalty"] = self.frequency_penalty
        if self.seed is not None:
            result["seed"] = self.seed
        effective_thinking = self.supports_thinking
        if effective_thinking is None:
            effective_thinking = detect_supports_thinking(self.model)
        if thinking_effort != "off" and effective_thinking:
            result["reasoning_effort"] = thinking_effort
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


# Model name substrings known to support reasoning_effort / thinking params.
# Checked when ModelProfile.supports_thinking is None (auto-detect mode).
_THINKING_MODEL_PATTERNS: frozenset[str] = frozenset(
    {"o1", "o3", "qwq", "deepseek-r1", "claude-3-7"}
)


def detect_supports_thinking(model_name: str) -> bool:
    """True if model_name matches a known thinking-capable pattern."""
    lower = model_name.lower()
    return any(p in lower for p in _THINKING_MODEL_PATTERNS)


def _extract_thinking_from_api_model(model: dict[str, Any]) -> bool | None:
    """Extract thinking support from a single provider model dict.

    Returns True/False when the API gives a definitive answer, None when the
    data isn't conclusive (fall back to name-pattern in that case).

    Provider formats handled:
    - OpenRouter: ``supported_parameters`` is a comprehensive list — absence
      of "reasoning"/"reasoning_effort" means definitively not supported.
    - LM Studio v0: ``capabilities`` is a partial list ("chat", "tools" …) —
      presence of "reasoning" is conclusive, but absence is not (LM Studio
      doesn't advertise all caps). Return None so name-pattern can fill in.
    - Generic dict ``capabilities``: check "reasoning"/"thinking" keys.
    """
    # OpenRouter-style: authoritative list of supported inference parameters.
    supported = model.get("supported_parameters")
    if isinstance(supported, list):
        params = {str(p).lower() for p in supported}
        # Present but no reasoning param → provider says it's not supported.
        return bool(params & {"reasoning_effort", "reasoning"})

    # LM Studio / generic capability lists.
    caps = model.get("capabilities")
    if isinstance(caps, list):
        lower_caps = {str(c).lower() for c in caps}
        if lower_caps & {"reasoning", "thinking"}:
            return True
        # LM Studio omits caps it doesn't advertise — absence is not definitive.
        return None
    if isinstance(caps, dict):
        for key in ("reasoning", "thinking"):
            val = caps.get(key)
            if val is not None:
                return bool(val)

    return None


async def autodetect_supports_thinking(profile: ModelProfile, model_name: str) -> bool:
    """True if the model supports thinking/reasoning inference params.

    Detection order:
    1. Provider API metadata for the matched model (see _extract_thinking_from_api_model).
    2. Name-pattern fallback when the API gives no conclusive signal.

    model_name should be the *resolved* name (not the "auto" sentinel) so the
    API lookup can match the actual model id."""
    models = await _fetch_models(profile)
    # Prefer exact id match; fall back to first model (local servers serve one).
    target: dict[str, Any] | None = None
    for m in models:
        if m.get("id") == model_name:
            target = m
            break
    if target is None and models:
        target = models[0]
    if target is not None:
        api_result = _extract_thinking_from_api_model(target)
        if api_result is not None:
            return api_result
    # No conclusive API signal — fall back to name-pattern.
    return detect_supports_thinking(model_name)


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
