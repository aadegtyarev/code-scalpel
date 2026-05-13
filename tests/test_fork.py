"""Fork delegation — v0.10 framework + LocalMetaForker."""

from __future__ import annotations

from pathlib import Path

import pytest

from code_scalpel.agent import StepAgent
from code_scalpel.config import AgentConfig, AppConfig, ModelProfile
from code_scalpel.fork import (
    ForkError,
    ForkOption,
    ForkResolution,
    LocalMetaForker,
    _extract_json_object,
    _parse_resolver_reply,
)
from tests.mocks import MockLLMAdapter

_CONFIG = AppConfig(
    profiles={"local": ModelProfile(provider="lmstudio", model="local-model", temperature=0.1)},
    agent=AgentConfig(max_files=2, max_file_lines=50, enforce_read_before_show=False),
)


def test_dataclasses_are_frozen() -> None:
    """Spec is data, not state. A resolver that mutated its own
    inputs mid-run would be exactly the sort of bug this layer
    prevents."""
    from dataclasses import FrozenInstanceError

    opt = ForkOption(name="x", summary="s")
    with pytest.raises(FrozenInstanceError):
        opt.name = "y"  # type: ignore[misc]

    res = ForkResolution(chosen="x", reasoning="r")
    with pytest.raises(FrozenInstanceError):
        res.chosen = "y"  # type: ignore[misc]


def test_parse_strict_json() -> None:
    options = (ForkOption("a", ""), ForkOption("b", ""))
    res = _parse_resolver_reply('{"chosen":"a","reasoning":"because"}', options)
    assert res.chosen == "a"
    assert res.reasoning == "because"


def test_parse_strips_fence_and_preamble() -> None:
    """Weak models prepend `Here's my answer:` or wrap in
    ```json. The parser yanks the first balanced { … } out."""
    options = (ForkOption("psycopg2", ""), ForkOption("asyncpg", ""))
    reply = (
        "Sure, here's my pick:\n\n"
        "```json\n"
        '{"chosen": "asyncpg", "reasoning": "needs async"}\n'
        "```\n"
    )
    res = _parse_resolver_reply(reply, options)
    assert res.chosen == "asyncpg"


def test_parse_rejects_invalid_choice() -> None:
    """Resolver returning a name not in the option set is a hard
    error — `/go` must escalate instead of silently choosing
    something else."""
    options = (ForkOption("a", ""), ForkOption("b", ""))
    with pytest.raises(ForkError):
        _parse_resolver_reply('{"chosen": "c", "reasoning": ""}', options)


def test_parse_rejects_non_json() -> None:
    options = (ForkOption("a", ""),)
    with pytest.raises(ForkError):
        _parse_resolver_reply("there is no choice here, just words", options)


def test_extract_json_object_handles_strings_with_braces() -> None:
    """Braces inside string literals must not throw off the
    bracket counter — `{"q":"a{b}c"}` is valid JSON."""
    src = '{"q": "a{b}c", "n": 1}'
    assert _extract_json_object(src) == src


def test_extract_json_object_picks_first_balanced() -> None:
    """Several JSON objects in the stream — return the first
    complete one. Saves us from concatenating two answers."""
    src = 'noise {"a":1} more noise {"b":2}'
    assert _extract_json_object(src) == '{"a":1}'


@pytest.fixture
def project(tmp_path: Path) -> Path:
    return tmp_path


@pytest.mark.asyncio
async def test_local_meta_forker_resolves(project: Path) -> None:
    """End-to-end: agent + LocalMetaForker pick the option the
    mock LLM returns, at temperature 0.0, with sampler-enforced
    structured output (`response_format=json_schema`)."""
    llm = MockLLMAdapter(['{"chosen": "asyncpg", "reasoning": "non-blocking I/O"}'])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)
    forker = LocalMetaForker(agent)

    res = await forker.resolve(
        question="Which Postgres client?",
        options=(
            ForkOption("psycopg2", "synchronous, widely used"),
            ForkOption("asyncpg", "async, faster on hot paths"),
        ),
        context="Project is asyncio-first.",
    )

    assert res.chosen == "asyncpg"
    assert "I/O" in res.reasoning
    assert llm.kwargs_calls[0]["temperature"] == 0.0
    # Structured output schema must be threaded through — that's what
    # probe_forks.py showed is the most reliable format on 14b. Drop
    # this assert and the resolver silently regresses to JSON-via-
    # prompt, which loses ~30% latency and gains parse-error risk.
    rf = llm.kwargs_calls[0].get("response_format")
    assert rf is not None
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["name"] == "fork_local_meta"
    assert rf["json_schema"]["strict"] is True


@pytest.mark.asyncio
async def test_local_meta_forker_empty_options(project: Path) -> None:
    """Empty options is a programmer error — we raise ForkError
    rather than silently make something up."""
    llm = MockLLMAdapter(["unused"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)
    forker = LocalMetaForker(agent)

    with pytest.raises(ForkError):
        await forker.resolve("question?", (), "ctx")


@pytest.mark.asyncio
async def test_local_meta_forker_passes_options_to_model(project: Path) -> None:
    """The user message sent to the LLM must include every option's
    name + summary — otherwise the resolver picks blind."""
    llm = MockLLMAdapter(['{"chosen": "a", "reasoning": "tie"}'])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)
    forker = LocalMetaForker(agent)

    await forker.resolve(
        question="any?",
        options=(
            ForkOption("a", "first one"),
            ForkOption("b", "second one"),
        ),
        context="ctx",
    )

    user_msg = llm.calls[0][-1]["content"]
    assert "first one" in user_msg
    assert "second one" in user_msg
