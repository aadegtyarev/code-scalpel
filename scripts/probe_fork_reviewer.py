"""Probe: does qwen2.5-coder-14b actually push back when the picker
chose poorly, or does it rubber-stamp `confirm` every time?

If 14b always confirms, the whole ReviewedAuto pipeline is theatre —
we'd be spending tokens on a pass that never disagrees. This probe
runs the same reviewer prompt on three classes of test case:

  CONFIRM-cases — picker chose a good option for the context.
                 Expected verdict: `confirm`.
  OVERRIDE-cases — picker chose the WRONG option (one whose summary
                  contradicts a constraint in the context).
                  Expected verdict: `override` with the right
                  alternative.
  DISCUSS-cases — genuine judgement calls (tie-or-close situations).
                 Expected verdict: `discuss`.

Metrics:
  - precision on each verdict (how often it's correct when given)
  - rubber-stamp rate (fraction of OVERRIDE-cases where the reviewer
    confirmed anyway — the failure mode we're guarding against)
  - alternative-name accuracy on overrides

Output uses LM Studio's structured-output (response_format=
json_schema) — same path the production code will use.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any

import openai

LMSTUDIO_BASE = "http://localhost:1234/v1"
MODEL_ID = "qwen/qwen2.5-coder-14b"


@dataclass(frozen=True)
class ReviewCase:
    name: str
    question: str
    options: tuple[tuple[str, str], ...]
    context: str
    picker_choice: str
    picker_reasoning: str
    expected_verdict: str  # "confirm" / "override" / "discuss"
    expected_alternative: str = ""  # required when expected_verdict=override


CASES: tuple[ReviewCase, ...] = (
    # ── CONFIRM-cases: picker chose well ─────────────────────────
    ReviewCase(
        name="confirm_asyncpg_for_asyncio",
        question="Which Postgres driver?",
        options=(
            ("psycopg2", "synchronous, mature"),
            ("asyncpg", "async-native, faster on hot paths"),
        ),
        context="Project is asyncio-first FastAPI service.",
        picker_choice="asyncpg",
        picker_reasoning="async-native matches the asyncio stack",
        expected_verdict="confirm",
    ),
    ReviewCase(
        name="confirm_pytest_for_greenfield",
        question="Test runner for new CLI?",
        options=(
            ("pytest", "rich fixtures, parametrize"),
            ("unittest", "stdlib, no install"),
        ),
        context="Greenfield Python 3.12 CLI, no existing tests.",
        picker_choice="pytest",
        picker_reasoning="standard tooling, easy parametrize",
        expected_verdict="confirm",
    ),
    # ── OVERRIDE-cases: picker chose against a clear constraint ──
    ReviewCase(
        name="override_async_into_sync_context",
        question="Which Postgres driver?",
        options=(
            ("psycopg2", "synchronous, mature"),
            ("asyncpg", "async-native"),
        ),
        context=(
            "Project is a synchronous CLI tool. We have no asyncio "
            "loop, will not introduce one. The driver runs in a "
            "plain `def main()` function."
        ),
        picker_choice="asyncpg",
        picker_reasoning="modern async-native API",
        expected_verdict="override",
        expected_alternative="psycopg2",
    ),
    ReviewCase(
        name="override_cloud_under_offline_constraint",
        question="Storage backend for the cache?",
        options=(
            ("sqlite", "embedded file, no server"),
            ("redis", "in-memory, requires server"),
            ("s3", "cloud object store"),
        ),
        context=(
            "Tool runs OFFLINE on developer laptops. No network, no "
            "external services. Cache must survive process restarts."
        ),
        picker_choice="s3",
        picker_reasoning="scalable cloud storage",
        expected_verdict="override",
        expected_alternative="sqlite",
    ),
    ReviewCase(
        name="override_framework_for_no_framework",
        question="Web framework?",
        options=(
            ("flask", "lightweight"),
            ("django", "batteries included"),
            ("none", "stdlib http.server"),
        ),
        context=(
            "Tool is a single localhost debug endpoint, runs offline, "
            "no auth, no DB. The user explicitly asked NOT to add a "
            "web framework dependency."
        ),
        picker_choice="flask",
        picker_reasoning="popular and lightweight",
        expected_verdict="override",
        expected_alternative="none",
    ),
    # ── DISCUSS-cases: genuine judgement calls ───────────────────
    ReviewCase(
        name="discuss_sync_http_client",
        question="HTTP client for a small sync script?",
        options=(
            ("requests", "synchronous, ergonomic"),
            ("httpx", "modern, async-and-sync, slightly heavier"),
        ),
        context=(
            "One-off script, 3 REST calls, no async loop. Either "
            "option works fine; team preference uncertain."
        ),
        picker_choice="requests",
        picker_reasoning="simpler, fewer deps",
        expected_verdict="discuss",
    ),
)


SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdict": {
            "type": "string",
            "enum": ["confirm", "override", "discuss"],
        },
        "alternative": {"type": "string"},
        "reasoning": {"type": "string"},
    },
    "required": ["verdict", "alternative", "reasoning"],
    "additionalProperties": False,
}


def _load_reviewer_prompt() -> str:
    from code_scalpel.prompts import FORK_REVIEWER

    return FORK_REVIEWER


def _user_message(case: ReviewCase) -> str:
    options_block = "\n".join(f"- {name}: {summary}" for name, summary in case.options)
    return (
        f"Question:\n{case.question}\n\n"
        f"Options:\n{options_block}\n\n"
        f"Context:\n{case.context}\n\n"
        f"Picker's choice: {case.picker_choice}\n"
        f"Picker's reasoning: {case.picker_reasoning}\n"
    )


async def call_reviewer(
    client: openai.AsyncOpenAI,
    case: ReviewCase,
    *,
    temperature: float,
) -> tuple[dict[str, Any] | None, int, float]:
    t0 = time.monotonic()
    try:
        resp = await client.chat.completions.create(
            model=MODEL_ID,
            messages=[
                {"role": "system", "content": _load_reviewer_prompt()},
                {"role": "user", "content": _user_message(case)},
            ],
            temperature=temperature,
            max_tokens=200,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "review",
                    "strict": True,
                    "schema": SCHEMA,
                },
            },
        )
    except Exception:
        return None, 0, time.monotonic() - t0
    dt = time.monotonic() - t0
    raw = resp.choices[0].message.content or ""
    try:
        return json.loads(raw), (resp.usage.completion_tokens if resp.usage else 0), dt
    except json.JSONDecodeError:
        return None, (resp.usage.completion_tokens if resp.usage else 0), dt


@dataclass
class Result:
    case: str
    expected: str
    got: str
    alt_got: str
    alt_match: bool
    latency_s: float
    tokens: int


async def run_temperature(client: openai.AsyncOpenAI, temperature: float) -> list[Result]:
    out: list[Result] = []
    print(f"\n── Temperature {temperature} ──")
    for case in CASES:
        data, tokens, dt = await call_reviewer(client, case, temperature=temperature)
        if data is None:
            print(f"  {case.name:<42} ERROR")
            continue
        verdict = data.get("verdict", "")
        alt = data.get("alternative", "")
        alt_match = case.expected_verdict != "override" or alt == case.expected_alternative
        out.append(
            Result(
                case=case.name,
                expected=case.expected_verdict,
                got=verdict,
                alt_got=alt,
                alt_match=alt_match,
                latency_s=dt,
                tokens=tokens,
            )
        )
        marker = "✓" if verdict == case.expected_verdict else "✗"
        alt_marker = (
            ""
            if case.expected_verdict != "override"
            else f" alt={alt!r} match={'✓' if alt_match else '✗'}"
        )
        print(
            f"  {case.name:<42} {marker} expected={case.expected_verdict:<8} "
            f"got={verdict:<8}{alt_marker} {dt:.1f}s/{tokens}tok"
        )
    return out


def summary(results: list[Result], temperature: float) -> str:
    total = len(results)
    correct = sum(r.expected == r.got for r in results)
    confirm_rs = sum(r.got == "confirm" for r in results if r.expected == "override")
    total_overrides = sum(1 for r in results if r.expected == "override")
    alt_correct = sum(r.alt_match for r in results if r.expected == "override")
    return (
        f"t={temperature}: "
        f"correct {correct}/{total}  "
        f"rubber-stamp on overrides {confirm_rs}/{total_overrides}  "
        f"alt-name correct {alt_correct}/{total_overrides}"
    )


async def main() -> None:
    client = openai.AsyncOpenAI(base_url=LMSTUDIO_BASE, api_key="not-needed")
    print(f"Model: {MODEL_ID}")
    print(f"Cases: {len(CASES)} × 3 temperatures = {len(CASES) * 3} calls")

    all_results: dict[float, list[Result]] = {}
    for t in (0.0, 0.3, 0.5):
        all_results[t] = await run_temperature(client, t)

    print("\n=== SUMMARY ===")
    for t in (0.0, 0.3, 0.5):
        if all_results[t]:
            print(f"  {summary(all_results[t], t)}")


if __name__ == "__main__":
    asyncio.run(main())
