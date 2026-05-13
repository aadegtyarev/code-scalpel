"""Probe: how well does qwen2.5-coder-14b handle fork decisions
under three output formats?

Run: `source .venv/bin/activate && python scripts/probe_forks.py`
Requires LM Studio at http://localhost:1234 with qwen2.5-coder-14b
loaded.

Three formats compared on the same fork test set:

  A. JSON via prompt — current v0.10 draft. Asks the model to
     output `{"chosen": "...", "reasoning": "..."}`. Weak on 14b:
     stray prose, fenced blocks, hallucinated keys.
  B. Plain text — `Pick: X\\nWhy: Y`. Closer to natural language,
     simple regex parser, no escape headaches.
  C. Structured output — LM Studio's `response_format={"type":
     "json_schema", ...}` enforces the schema at sampler time.
     Guaranteed valid JSON if the provider supports it (LM Studio
     does since 0.3.x).

Metrics per format:
  - parse_ok        — output parsed into (chosen, reasoning)
  - choice_valid    — `chosen` is one of the listed options
  - reasoning_lines — count (rule says ≤ 3)
  - latency_s       — wall time
  - tokens_out      — completion tokens

Test cases are realistic dev forks the agent would hit on a real
project: DB driver, HTTP client, test runner, ORM. Each case has
an obvious wrong answer to flush out rubber-stamping.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from typing import Any

import openai

LMSTUDIO_BASE = "http://localhost:1234/v1"
MODEL_ID = "qwen/qwen2.5-coder-14b"


@dataclass(frozen=True)
class ForkCase:
    name: str
    question: str
    options: tuple[tuple[str, str], ...]  # (name, summary)
    context: str
    # Names the picker SHOULD prefer given the context — for sanity
    # scoring. Not a hard pass/fail (judgement varies), but if the
    # model picks anything else we want to see why.
    expected_in: tuple[str, ...]


CASES: tuple[ForkCase, ...] = (
    ForkCase(
        name="asyncio_db_driver",
        question="Which Postgres driver should we use?",
        options=(
            ("psycopg2", "synchronous, mature, widely used"),
            ("asyncpg", "async-native, faster on hot paths"),
            ("sqlalchemy", "ORM with both sync and async backends"),
        ),
        context=(
            "Project is asyncio-first FastAPI service. No ORM needed; "
            "we want raw SQL with parameter binding for two tables."
        ),
        expected_in=("asyncpg",),
    ),
    ForkCase(
        name="cli_test_runner",
        question="Which test runner for this CLI tool?",
        options=(
            ("pytest", "de-facto standard, rich fixtures, parametrize"),
            ("unittest", "stdlib, no install, class-based"),
            ("nose2", "older fork of nose, niche"),
        ),
        context="Greenfield Python 3.12 CLI tool, no existing tests yet.",
        expected_in=("pytest",),
    ),
    ForkCase(
        name="sync_http_client",
        question="HTTP client for a small sync script?",
        options=(
            ("requests", "synchronous, ergonomic, stdlib feel"),
            ("httpx", "async-and-sync, modern, slightly heavier"),
            ("urllib", "stdlib, verbose, no install"),
        ),
        context=(
            "One-off script, hits 3 REST endpoints, no async loop in "
            "the project. Wants to ship fast, no extra hardening."
        ),
        expected_in=("requests", "httpx"),
    ),
    ForkCase(
        name="constrained_choice",
        question="Web framework for an offline-only desktop tool?",
        options=(
            ("flask", "lightweight, lots of tutorials"),
            ("django", "batteries included"),
            ("none", "no web framework needed, use stdlib http.server"),
        ),
        context=(
            "Tool runs offline on developer machines, no auth, no DB, "
            "single endpoint for a localhost debug UI."
        ),
        # The clue is "no web framework needed" — model should pick `none`.
        expected_in=("none",),
    ),
)


PROMPT_JSON = """\
You are an architect. Pick ONE option from the list.

Rules:
- Choose exactly one of the option names verbatim.
- Explain in at most 3 short lines.
- No code, no preamble, no fence.

Output JSON (no fences, no extra text):
{"chosen": "<exact option name>", "reasoning": "<3 lines max>"}
"""


PROMPT_TEXT = """\
You are an architect. Pick ONE option from the list.

Rules:
- First line is exactly: Pick: <option name>
- Then up to 3 lines starting with "Why:" explaining the choice.
- No code, no preamble, no markdown fence.

Example:
Pick: foo
Why: it fits the constraint.
Why: the alternative breaks under X.
"""


PROMPT_STRUCTURED = """\
You are an architect. Pick ONE option from the list.

Rules:
- Choose exactly one of the option names verbatim.
- Explain in at most 3 short lines.
- No code, no preamble.
"""


SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "chosen": {"type": "string"},
        "reasoning": {"type": "string"},
    },
    "required": ["chosen", "reasoning"],
    "additionalProperties": False,
}


def _user_message(case: ForkCase) -> str:
    options_block = "\n".join(f"- {name}: {summary}" for name, summary in case.options)
    return f"Question:\n{case.question}\n\nOptions:\n{options_block}\n\nContext:\n{case.context}\n"


async def call_llm(
    client: openai.AsyncOpenAI,
    *,
    system: str,
    user: str,
    structured: bool = False,
) -> tuple[str, int, float]:
    """Single LLM call. Returns (text, completion_tokens, latency_s)."""
    kwargs: dict[str, Any] = {
        "model": MODEL_ID,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.0,
        "max_tokens": 200,
    }
    if structured:
        kwargs["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "fork_resolution",
                "strict": True,
                "schema": SCHEMA,
            },
        }
    t0 = time.monotonic()
    resp = await client.chat.completions.create(**kwargs)
    dt = time.monotonic() - t0
    text = resp.choices[0].message.content or ""
    tokens = resp.usage.completion_tokens if resp.usage else 0
    return text, tokens, dt


_TEXT_PICK_RE = re.compile(r"^\s*Pick:\s*(.+?)\s*$", re.MULTILINE)


def parse_text(reply: str) -> tuple[str, str] | None:
    """Parse `Pick: X\\nWhy: ...` format. Returns (chosen, reasoning) or None."""
    m = _TEXT_PICK_RE.search(reply)
    if not m:
        return None
    chosen = m.group(1).strip().strip("`'\"")
    reasoning = "\n".join(
        line.strip().removeprefix("Why:").strip()
        for line in reply.splitlines()
        if line.strip().startswith("Why:")
    )
    return chosen, reasoning


def parse_json_loose(reply: str) -> tuple[str, str] | None:
    """Brace-tracking JSON extract — same code path as fork.py."""
    in_string = False
    escape = False
    start = -1
    depth = 0
    payload: str | None = None
    for i, ch in enumerate(reply):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                payload = reply[start : i + 1]
                break
    if payload is None:
        return None
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None
    chosen = str(data.get("chosen", "")).strip()
    reasoning = str(data.get("reasoning", "")).strip()
    if not chosen:
        return None
    return chosen, reasoning


@dataclass
class CaseResult:
    case: str
    format: str
    parse_ok: bool
    chosen: str
    valid_choice: bool
    expected_match: bool
    reasoning_lines: int
    tokens_out: int
    latency_s: float
    raw_excerpt: str


async def run_one(
    client: openai.AsyncOpenAI,
    case: ForkCase,
    fmt: str,
) -> CaseResult:
    user = _user_message(case)
    if fmt == "json":
        text, tokens, dt = await call_llm(client, system=PROMPT_JSON, user=user, structured=False)
        parsed = parse_json_loose(text)
    elif fmt == "text":
        text, tokens, dt = await call_llm(client, system=PROMPT_TEXT, user=user, structured=False)
        parsed = parse_text(text)
    elif fmt == "structured":
        text, tokens, dt = await call_llm(
            client, system=PROMPT_STRUCTURED, user=user, structured=True
        )
        parsed = parse_json_loose(text)
    else:
        raise ValueError(fmt)

    if parsed is None:
        return CaseResult(
            case=case.name,
            format=fmt,
            parse_ok=False,
            chosen="",
            valid_choice=False,
            expected_match=False,
            reasoning_lines=0,
            tokens_out=tokens,
            latency_s=dt,
            raw_excerpt=text[:200],
        )

    chosen, reasoning = parsed
    option_names = {name for name, _ in case.options}
    valid = chosen in option_names
    matches = chosen in case.expected_in
    lines = sum(1 for line in reasoning.splitlines() if line.strip())
    return CaseResult(
        case=case.name,
        format=fmt,
        parse_ok=True,
        chosen=chosen,
        valid_choice=valid,
        expected_match=matches,
        reasoning_lines=lines,
        tokens_out=tokens,
        latency_s=dt,
        raw_excerpt=text[:200],
    )


def summary_row(results: list[CaseResult]) -> str:
    fmt = results[0].format
    n = len(results)
    parsed = sum(r.parse_ok for r in results)
    valid = sum(r.valid_choice for r in results)
    expected = sum(r.expected_match for r in results)
    avg_lat = sum(r.latency_s for r in results) / n if n else 0
    avg_tok = sum(r.tokens_out for r in results) / n if n else 0
    return (
        f"  {fmt:<11} "
        f"parse {parsed}/{n}  "
        f"valid {valid}/{n}  "
        f"matched-expected {expected}/{n}  "
        f"avg {avg_lat:.1f}s / {avg_tok:.0f}tok"
    )


async def main() -> None:
    client = openai.AsyncOpenAI(base_url=LMSTUDIO_BASE, api_key="not-needed")

    print(f"Model: {MODEL_ID}")
    print(f"Cases: {len(CASES)} × 3 formats = {len(CASES) * 3} calls\n")

    all_results: dict[str, list[CaseResult]] = {"json": [], "text": [], "structured": []}
    for case in CASES:
        print(f"=== {case.name} ===")
        for fmt in ("json", "text", "structured"):
            try:
                r = await run_one(client, case, fmt)
            except Exception as e:
                print(f"  {fmt:<11} ERROR: {e}")
                continue
            all_results[fmt].append(r)
            tick = "✓" if r.parse_ok and r.valid_choice else "✗"
            print(
                f"  {fmt:<11} {tick} chose={r.chosen!r:<14} "
                f"valid={r.valid_choice} expected={r.expected_match} "
                f"lines={r.reasoning_lines} {r.latency_s:.1f}s/{r.tokens_out}tok"
            )
            if not r.parse_ok:
                print(f"    raw: {r.raw_excerpt!r}")
        print()

    print("=== SUMMARY ===")
    for fmt in ("json", "text", "structured"):
        if all_results[fmt]:
            print(summary_row(all_results[fmt]))


if __name__ == "__main__":
    asyncio.run(main())
