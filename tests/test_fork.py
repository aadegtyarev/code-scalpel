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


# ── HumanForker (trust-aware ChoiceCard resolver) ─────────────────────────────


@pytest.mark.asyncio
async def test_human_forker_yolo_skips_card_for_non_critical(project: Path) -> None:
    """trust=yolo + critical=False → straight to LocalMetaForker;
    UI hook is never called. /go on autopilot shouldn't pause on a
    routine architectural question."""
    from code_scalpel.fork import HumanForker

    llm = MockLLMAdapter(['{"chosen": "a", "reasoning": "ok"}'])
    cfg = AppConfig(
        profiles={"local": ModelProfile(provider="lmstudio", model="m")},
        agent=AgentConfig(trust="yolo", enforce_read_before_show=False),
    )
    agent = StepAgent(llm=llm, cwd=project, config=cfg)
    calls: list[tuple] = []  # type: ignore[type-arg]

    async def fake_hook(_t, _o, _to):  # type: ignore[no-untyped-def]
        calls.append((_t, _o, _to))
        return "a"

    forker = HumanForker(agent, ui_hook=fake_hook, config=cfg.agent)
    res = await forker.resolve(
        "q",
        (ForkOption("a", "x"), ForkOption("b", "y")),
        "ctx",
        critical=False,
    )

    assert res.chosen == "a"
    assert calls == []


@pytest.mark.asyncio
async def test_human_forker_yolo_renders_card_for_critical(project: Path) -> None:
    """trust=yolo + critical=True → card with yolo-critical timeout."""
    from code_scalpel.fork import HumanForker

    llm = MockLLMAdapter(["unused"])
    cfg = AppConfig(
        profiles={"local": ModelProfile(provider="lmstudio", model="m")},
        agent=AgentConfig(
            trust="yolo",
            fork_human_timeout_yolo_critical=60,
            enforce_read_before_show=False,
        ),
    )
    agent = StepAgent(llm=llm, cwd=project, config=cfg)
    captured: dict = {}  # type: ignore[type-arg]

    async def fake_hook(_title, _options, timeout):  # type: ignore[no-untyped-def]
        captured["timeout"] = timeout
        return "a"

    forker = HumanForker(agent, ui_hook=fake_hook, config=cfg.agent)
    res = await forker.resolve(
        "q",
        (ForkOption("a", "x"), ForkOption("b", "y")),
        "ctx",
        critical=True,
    )

    assert res.chosen == "a"
    assert captured["timeout"] == 60


@pytest.mark.asyncio
async def test_human_forker_skeptic_no_timeout(project: Path) -> None:
    """trust=skeptic → card with `timeout=None`; user MUST answer."""
    from code_scalpel.fork import HumanForker

    llm = MockLLMAdapter(["unused"])
    cfg = AppConfig(
        profiles={"local": ModelProfile(provider="lmstudio", model="m")},
        agent=AgentConfig(trust="skeptic", enforce_read_before_show=False),
    )
    agent = StepAgent(llm=llm, cwd=project, config=cfg)
    captured: dict = {}  # type: ignore[type-arg]

    async def fake_hook(_title, _options, timeout):  # type: ignore[no-untyped-def]
        captured["timeout"] = timeout
        return "b"

    forker = HumanForker(agent, ui_hook=fake_hook, config=cfg.agent)
    res = await forker.resolve(
        "q",
        (ForkOption("a", "x"), ForkOption("b", "y")),
        "ctx",
    )

    assert res.chosen == "b"
    assert captured["timeout"] is None


@pytest.mark.asyncio
async def test_human_forker_timeout_falls_through_to_auto(project: Path) -> None:
    """trust=optimist; ui_hook returns None (timeout) → LocalMetaForker
    picks via the same model in architect mode."""
    from code_scalpel.fork import HumanForker

    llm = MockLLMAdapter(['{"chosen": "b", "reasoning": "auto-pick"}'])
    cfg = AppConfig(
        profiles={"local": ModelProfile(provider="lmstudio", model="m")},
        agent=AgentConfig(trust="optimist", enforce_read_before_show=False),
    )
    agent = StepAgent(llm=llm, cwd=project, config=cfg)

    async def fake_hook(_t, _o, _to):  # type: ignore[no-untyped-def]
        return None  # simulate timeout

    forker = HumanForker(agent, ui_hook=fake_hook, config=cfg.agent)
    res = await forker.resolve(
        "q",
        (ForkOption("a", "x"), ForkOption("b", "y")),
        "ctx",
    )

    assert res.chosen == "b"
    assert "auto-pick" in res.reasoning


@pytest.mark.asyncio
async def test_human_forker_auto_key_delegates(project: Path) -> None:
    """User pressing `*` → LocalMetaForker on this single fork."""
    from code_scalpel.fork import HumanForker

    llm = MockLLMAdapter(['{"chosen": "a", "reasoning": "model picked"}'])
    cfg = AppConfig(
        profiles={"local": ModelProfile(provider="lmstudio", model="m")},
        agent=AgentConfig(trust="skeptic", enforce_read_before_show=False),
    )
    agent = StepAgent(llm=llm, cwd=project, config=cfg)

    async def fake_hook(_t, _o, _to):  # type: ignore[no-untyped-def]
        return "*"

    forker = HumanForker(agent, ui_hook=fake_hook, config=cfg.agent)
    res = await forker.resolve(
        "q",
        (ForkOption("a", "x"), ForkOption("b", "y")),
        "ctx",
    )

    assert res.chosen == "a"
    assert "model picked" in res.reasoning


@pytest.mark.asyncio
async def test_human_forker_clarify_loop(project: Path) -> None:
    """User presses `?` → clarify NarrowPass expands summaries → card
    re-renders → user then picks. The second hook call must see the
    EXPANDED descriptions."""
    from code_scalpel.fork import HumanForker

    expanded = (
        "**asyncpg**\n"
        "It is the right call when you need native async I/O.\n"
        "It bites when you also need ORM features.\n\n"
        "**psycopg2**\n"
        "It is the right call for synchronous workloads.\n"
        "It bites under high concurrency.\n"
    )
    llm = MockLLMAdapter([expanded])
    cfg = AppConfig(
        profiles={"local": ModelProfile(provider="lmstudio", model="m")},
        agent=AgentConfig(trust="skeptic", enforce_read_before_show=False),
    )
    agent = StepAgent(llm=llm, cwd=project, config=cfg)

    seen_summaries: list[list[str]] = []
    presses = iter(["?", "a"])

    async def fake_hook(_title, options, _to):  # type: ignore[no-untyped-def]
        seen_summaries.append([o.description for o in options])
        return next(presses)

    forker = HumanForker(agent, ui_hook=fake_hook, config=cfg.agent)
    res = await forker.resolve(
        "Which Postgres client?",
        (ForkOption("asyncpg", "async"), ForkOption("psycopg2", "sync")),
        "context",
    )

    assert res.chosen == "asyncpg"
    assert len(seen_summaries) == 2
    first = " ".join(seen_summaries[0])
    second = " ".join(seen_summaries[1])
    assert "async" in first
    assert "native async I/O" in second
    assert "synchronous workloads" in second


@pytest.mark.asyncio
async def test_human_forker_headless_falls_back_to_local_meta(project: Path) -> None:
    """No UI hook + policy=local_meta → LocalMetaForker picks; the
    run continues without a UI."""
    from code_scalpel.fork import HumanForker

    llm = MockLLMAdapter(['{"chosen": "a", "reasoning": "fallback"}'])
    cfg = AppConfig(
        profiles={"local": ModelProfile(provider="lmstudio", model="m")},
        agent=AgentConfig(
            trust="skeptic",
            fork_human_fallback="local_meta",
            enforce_read_before_show=False,
        ),
    )
    agent = StepAgent(llm=llm, cwd=project, config=cfg)
    forker = HumanForker(agent, ui_hook=None, config=cfg.agent)
    res = await forker.resolve(
        "q",
        (ForkOption("a", "x"), ForkOption("b", "y")),
        "ctx",
    )

    assert res.chosen == "a"


@pytest.mark.asyncio
async def test_human_forker_headless_error_policy_raises(project: Path) -> None:
    """No UI hook + policy=error → ForkError. Scripted runs that set
    this know an unresolvable fork should stop them."""
    from code_scalpel.fork import HumanForker

    llm = MockLLMAdapter(["unused"])
    cfg = AppConfig(
        profiles={"local": ModelProfile(provider="lmstudio", model="m")},
        agent=AgentConfig(
            trust="skeptic",
            fork_human_fallback="error",
            enforce_read_before_show=False,
        ),
    )
    agent = StepAgent(llm=llm, cwd=project, config=cfg)
    forker = HumanForker(agent, ui_hook=None, config=cfg.agent)
    with pytest.raises(ForkError):
        await forker.resolve(
            "q",
            (ForkOption("a", "x"), ForkOption("b", "y")),
            "ctx",
        )


# ── detect_forks (NarrowPass on top of /plan output) ──────────────────────────


@pytest.mark.asyncio
async def test_detect_forks_returns_empty_on_no_forks(project: Path) -> None:
    """Plan without architectural decisions → empty tuple. Detector
    must NOT invent forks (false positives are costlier than false
    negatives — each costs an LLM call + maybe a user prompt)."""
    from code_scalpel.fork import detect_forks

    llm = MockLLMAdapter(['{"forks": []}'])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    result = await detect_forks(agent, "## T001: Add docstring to greet()\n")

    assert result == ()


@pytest.mark.asyncio
async def test_detect_forks_parses_structured_output(project: Path) -> None:
    """Happy path — detector returns one fork with two options;
    we parse it into a ForkContext tuple ready for `runtime.fork()`."""
    from code_scalpel.fork import detect_forks

    payload = (
        '{"forks": ['
        '  {"question": "Which Postgres driver?",'
        '   "options": ['
        '     {"name": "psycopg2", "summary": "sync, mature"},'
        '     {"name": "asyncpg", "summary": "async, faster"}'
        "   ],"
        '   "context": "Project is asyncio-first."}'
        "]}"
    )
    llm = MockLLMAdapter([payload])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    result = await detect_forks(
        agent,
        "## T001: Add Postgres support\n",
        "FastAPI project, asyncio-first.",
    )

    assert len(result) == 1
    fork = result[0]
    assert fork.question == "Which Postgres driver?"
    assert len(fork.options) == 2
    assert fork.options[0].name == "psycopg2"
    assert fork.options[1].name == "asyncpg"
    assert "asyncio-first" in fork.context


@pytest.mark.asyncio
async def test_detect_forks_drops_degenerate_single_option(project: Path) -> None:
    """A 'fork' with one option is just a recommendation. Drop it —
    Fork API needs ≥2 options or there's nothing to delegate."""
    from code_scalpel.fork import detect_forks

    payload = (
        '{"forks": ['
        '  {"question": "Which X?",'
        '   "options": [{"name": "only", "summary": "alone"}],'
        '   "context": "ctx"}'
        "]}"
    )
    llm = MockLLMAdapter([payload])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    result = await detect_forks(agent, "plan")

    assert result == ()


@pytest.mark.asyncio
async def test_detect_forks_survives_non_json(project: Path) -> None:
    """Detector misfires → return (). Plan flow must continue
    without architectural delegation, not crash."""
    from code_scalpel.fork import detect_forks

    llm = MockLLMAdapter(["sorry, no forks today"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    result = await detect_forks(agent, "plan")

    assert result == ()


@pytest.mark.asyncio
async def test_detect_forks_uses_structured_output(project: Path) -> None:
    """Schema lands in adapter kwargs — same path probe validated.
    Drop this assert and the detector silently regresses to
    JSON-via-prompt."""
    from code_scalpel.fork import detect_forks

    llm = MockLLMAdapter(['{"forks": []}'])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    await detect_forks(agent, "plan")

    rf = llm.kwargs_calls[0].get("response_format")
    assert rf is not None
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["name"] == "detect_forks"


# ── ReviewedAutoForker (picker + skeptic reviewer + anchor) ───────────────────


@pytest.mark.asyncio
async def test_reviewed_auto_confirm_returns_picker_choice(project: Path) -> None:
    """Picker picks A; reviewer confirms → ReviewedAuto returns A.
    The happy path: both passes agree, no override, no escalation."""
    from code_scalpel.fork import ReviewedAutoForker

    llm = MockLLMAdapter(
        [
            # picker output
            '{"chosen": "a", "reasoning": "fits the constraint"}',
            # reviewer output
            '{"verdict": "confirm", "alternative": "", "reasoning": "agrees"}',
        ]
    )
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)
    forker = ReviewedAutoForker(agent)

    res = await forker.resolve(
        "q",
        (ForkOption("a", "first"), ForkOption("b", "second")),
        "ctx",
    )

    assert res.chosen == "a"


@pytest.mark.asyncio
async def test_reviewed_auto_override_returns_alternative(project: Path) -> None:
    """Picker picks A; reviewer overrides to B → ReviewedAuto
    returns B. This is exactly the failure mode the second pass is
    there to catch: picker walked into a constraint."""
    from code_scalpel.fork import ReviewedAutoForker

    llm = MockLLMAdapter(
        [
            '{"chosen": "a", "reasoning": "looked fine"}',
            '{"verdict": "override", "alternative": "b", "reasoning": "constraint X rules out a"}',
        ]
    )
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)
    forker = ReviewedAutoForker(agent)

    res = await forker.resolve(
        "q",
        (ForkOption("a", "first"), ForkOption("b", "second")),
        "ctx",
    )

    assert res.chosen == "b"
    assert "constraint X" in res.reasoning


@pytest.mark.asyncio
async def test_reviewed_auto_discuss_anchors_to_picker(project: Path) -> None:
    """Picker picks A; reviewer says `discuss` → ReviewedAuto
    returns the picker's choice (it's stable, t=0.0). Inside the
    auto pipeline there's no human to escalate to; the anchor
    avoids a second-guessing loop."""
    from code_scalpel.fork import ReviewedAutoForker

    llm = MockLLMAdapter(
        [
            '{"chosen": "a", "reasoning": "fine"}',
            '{"verdict": "discuss", "alternative": "", "reasoning": "tie"}',
        ]
    )
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)
    forker = ReviewedAutoForker(agent)

    res = await forker.resolve(
        "q",
        (ForkOption("a", "first"), ForkOption("b", "second")),
        "ctx",
    )

    assert res.chosen == "a"
    assert "anchored" in res.reasoning


@pytest.mark.asyncio
async def test_reviewed_auto_override_to_unknown_demotes_to_discuss(
    project: Path,
) -> None:
    """Reviewer hallucinates an alternative name not in the option
    set → treat as `discuss` and anchor to picker. Trusting the
    invented name would silently corrupt the resolution."""
    from code_scalpel.fork import ReviewedAutoForker

    llm = MockLLMAdapter(
        [
            '{"chosen": "a", "reasoning": "ok"}',
            '{"verdict": "override", "alternative": "made-up", "reasoning": "imaginary"}',
        ]
    )
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)
    forker = ReviewedAutoForker(agent)

    res = await forker.resolve(
        "q",
        (ForkOption("a", "first"), ForkOption("b", "second")),
        "ctx",
    )

    assert res.chosen == "a"
    assert "anchored" in res.reasoning


@pytest.mark.asyncio
async def test_reviewed_auto_used_by_default_in_human_forker(project: Path) -> None:
    """`fork_auto_reviewed=True` (default) routes the auto pipeline
    through the picker+reviewer pair. The third LLM call is the
    reviewer; without it there'd only be two messages on the bus."""
    from code_scalpel.fork import HumanForker

    llm = MockLLMAdapter(
        [
            # picker
            '{"chosen": "a", "reasoning": "ok"}',
            # reviewer
            '{"verdict": "confirm", "alternative": "", "reasoning": "agrees"}',
        ]
    )
    cfg = AppConfig(
        profiles={"local": ModelProfile(provider="lmstudio", model="m")},
        agent=AgentConfig(
            trust="optimist",
            fork_auto_reviewed=True,
            enforce_read_before_show=False,
        ),
    )
    agent = StepAgent(llm=llm, cwd=project, config=cfg)

    async def fake_hook(_t, _o, _to):  # type: ignore[no-untyped-def]
        return "*"  # user delegates to auto

    forker = HumanForker(agent, ui_hook=fake_hook, config=cfg.agent)
    res = await forker.resolve(
        "q",
        (ForkOption("a", "x"), ForkOption("b", "y")),
        "ctx",
    )

    assert res.chosen == "a"
    assert len(llm.calls) == 2  # picker + reviewer


@pytest.mark.asyncio
async def test_fork_auto_reviewed_false_skips_reviewer(project: Path) -> None:
    """Opt-out flag — caller wants the single-pass LocalMeta path
    (faster, no override safety net). Only one LLM call, no reviewer."""
    from code_scalpel.fork import HumanForker

    llm = MockLLMAdapter(['{"chosen": "a", "reasoning": "ok"}'])
    cfg = AppConfig(
        profiles={"local": ModelProfile(provider="lmstudio", model="m")},
        agent=AgentConfig(
            trust="optimist",
            fork_auto_reviewed=False,
            enforce_read_before_show=False,
        ),
    )
    agent = StepAgent(llm=llm, cwd=project, config=cfg)

    async def fake_hook(_t, _o, _to):  # type: ignore[no-untyped-def]
        return "*"

    forker = HumanForker(agent, ui_hook=fake_hook, config=cfg.agent)
    res = await forker.resolve(
        "q",
        (ForkOption("a", "x"), ForkOption("b", "y")),
        "ctx",
    )

    assert res.chosen == "a"
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_run_plan_resolves_forks_when_enabled(project: Path) -> None:
    """Integration: auto_detect_forks=True + a resolver attached →
    run_plan inserts an «Architectural decisions» block at the top
    of TASKS.md before any task runs."""
    from code_scalpel.fork import HumanForker
    from code_scalpel.tools.shell import ShellResult
    from tests.mocks import MockShellRunner

    tasks_path = project / ".code-scalpel" / "TASKS.md"
    tasks_path.parent.mkdir(parents=True, exist_ok=True)
    tasks_path.write_text(
        "## T001: Wire Postgres support\n\n"
        "Goal: connect to db\n"
        "Files: db.py\n"
        "Acceptance:\n"
        "- imports cleanly\n"
        "Test command: pytest\n"
    )

    detect_payload = (
        '{"forks": ['
        '  {"question": "Which Postgres driver?",'
        '   "options": ['
        '     {"name": "psycopg2", "summary": "sync"},'
        '     {"name": "asyncpg", "summary": "async"}'
        "   ],"
        '   "context": "FastAPI asyncio service."}'
        "]}"
    )
    # detect_forks + resolver (LocalMetaForker default, no
    # reviewer for this test) + builder.
    patch = """\
db.py
```python
<<<<<<< SEARCH
=======
import asyncpg
>>>>>>> REPLACE
```
"""
    llm = MockLLMAdapter(
        [
            detect_payload,
            # LocalMetaForker (auto-reviewed off for simplicity)
            '{"chosen": "asyncpg", "reasoning": "asyncio match"}',
            patch,
        ]
    )
    shell = MockShellRunner([ShellResult("1 passed", 0)])
    cfg = AppConfig(
        profiles={"local": ModelProfile(provider="lmstudio", model="local-model", temperature=0.1)},
        agent=AgentConfig(
            max_files=2,
            max_file_lines=50,
            max_debug_attempts=0,
            iterative_patch_loop=True,
            enforce_read_before_show=False,
            auto_git=False,
            sandbox="off",
            auto_annotate_plan=False,
            auto_detect_forks=True,
            fork_auto_reviewed=False,  # one LLM call for picker, not two
            fork_human_fallback="local_meta",
            trust="optimist",
        ),
    )
    agent = StepAgent(llm=llm, cwd=project, config=cfg, shell_runner=shell)
    resolver = HumanForker(agent, ui_hook=None, config=cfg.agent)

    result = await agent.run_plan(fork_resolver=resolver)

    final = (project / ".code-scalpel" / "TASKS.md").read_text()
    assert "## Architectural decisions" in final
    assert "asyncpg" in final
    assert "Which Postgres driver?" in final
    assert result.tasks_completed == 1


# ── UpstreamForker (native LM Studio + OpenAI-compat fallback) ────────────────


@pytest.mark.asyncio
async def test_upstream_forker_lmstudio_streams_native_events(project: Path) -> None:
    """Native path: upstream URL ends in /v1 → goes through
    /api/v1/chat. Event_sink receives every event; final
    resolution comes from the message.delta accumulation."""
    import httpx

    from code_scalpel.fork import UpstreamForker, UpstreamProfile

    sse_body = (
        b'data: {"type": "chat.start", "model_instance_id": "i1"}\n'
        b'data: {"type": "model_load.start", "model_instance_id": "i1"}\n'
        b'data: {"type": "model_load.progress", "progress": 0.5}\n'
        b'data: {"type": "model_load.end", "load_time_seconds": 8.0}\n'
        b'data: {"type": "message.start"}\n'
        b'data: {"type": "message.delta", "content": '
        b'"{\\"chosen\\": \\"asyncpg\\", \\"reasoning\\": \\"native I/O\\"}"}\n'
        b'data: {"type": "message.end"}\n'
        b'data: {"type": "chat.end", "result": {"usage": '
        b'{"prompt_tokens": 100, "completion_tokens": 20}, '
        b'"total_time_seconds": 10.0}}\n'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert "/api/v1/chat" in str(request.url)
        return httpx.Response(200, content=sse_body, headers={"content-type": "text/event-stream"})

    captured_events: list[object] = []

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        forker = UpstreamForker(
            UpstreamProfile(
                base_url="http://localhost:1234/v1",
                model="gemma-26b",
                ttl_seconds=300,
            ),
            event_sink=captured_events.append,
            http_client=client,
        )
        res = await forker.resolve(
            "Which Postgres driver?",
            (ForkOption("psycopg2", "sync"), ForkOption("asyncpg", "async")),
            "asyncio service",
        )

    assert res.chosen == "asyncpg"
    assert "native I/O" in res.reasoning
    # event_sink saw the load events — that's what OperationCard
    # will consume to render phase bars.
    type_names = [type(e).__name__ for e in captured_events]
    assert "ModelLoadProgress" in type_names
    assert "ModelLoadEnd" in type_names
    assert "ChatEnd" in type_names


@pytest.mark.asyncio
async def test_upstream_forker_raises_on_stream_error(project: Path) -> None:
    """Native server emitted an `error` event mid-stream — we
    surface it as ForkError. Caller can mark the fork unresolved
    in the final summary (mark-for-review pattern from v0.12)."""
    import httpx

    from code_scalpel.fork import ForkError, UpstreamForker, UpstreamProfile

    sse_body = (
        b'data: {"type": "chat.start", "model_instance_id": "i1"}\n'
        b'data: {"type": "error", "error": "out of memory"}\n'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=sse_body, headers={"content-type": "text/event-stream"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        forker = UpstreamForker(
            UpstreamProfile(base_url="http://localhost:1234/v1", model="x"),
            http_client=client,
        )
        with pytest.raises(ForkError) as exc:
            await forker.resolve(
                "q",
                (ForkOption("a", ""), ForkOption("b", "")),
                "ctx",
            )
    assert "out of memory" in str(exc.value)


@pytest.mark.asyncio
async def test_upstream_forker_passes_ttl_in_request(project: Path) -> None:
    """`ttl_seconds` from the upstream profile lands in the native
    chat request body. This is how the model «lingers» between
    batched forks — if we don't pass it, every fork triggers a
    fresh cold load.
    """
    import json as _json

    import httpx

    from code_scalpel.fork import UpstreamForker, UpstreamProfile

    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(_json.loads(request.content))
        return httpx.Response(
            200,
            content=(
                b'data: {"type": "chat.start", "model_instance_id": "i"}\n'
                b'data: {"type": "message.delta", "content": '
                b'"{\\"chosen\\": \\"a\\", \\"reasoning\\": \\"ok\\"}"}\n'
                b'data: {"type": "chat.end", "result": {}}\n'
            ),
            headers={"content-type": "text/event-stream"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        forker = UpstreamForker(
            UpstreamProfile(base_url="http://localhost:1234/v1", model="x", ttl_seconds=600),
            http_client=client,
        )
        await forker.resolve("q", (ForkOption("a", ""), ForkOption("b", "")), "ctx")

    assert captured["ttl"] == 600
    # Structured output schema travels too — same shape LocalMeta uses.
    rf = captured["response_format"]
    assert isinstance(rf, dict) and rf["type"] == "json_schema"


def test_upstream_forker_detects_lmstudio_url() -> None:
    """Trailing /v1 is the LM Studio convention. Other providers
    (Anthropic /v1/messages, OpenAI /v1/chat/completions) get the
    OpenAI-compat fallback — but those URLs don't end in plain
    /v1 either (they keep the suffix path). Detection is the
    cheap routing key."""
    from code_scalpel.fork import UpstreamForker

    assert UpstreamForker._is_lmstudio_url("http://localhost:1234/v1") is True
    assert UpstreamForker._is_lmstudio_url("http://localhost:1234/v1/") is True
    assert UpstreamForker._is_lmstudio_url("https://api.openai.com/v1/chat/completions") is False
    assert UpstreamForker._is_lmstudio_url("https://api.anthropic.com") is False


@pytest.mark.asyncio
async def test_human_forker_esc_raises(project: Path) -> None:
    """User pressed Escape → ForkError so the caller can choose to
    retry, fall back, or bubble."""
    from code_scalpel.fork import HumanForker

    llm = MockLLMAdapter(["unused"])
    cfg = AppConfig(
        profiles={"local": ModelProfile(provider="lmstudio", model="m")},
        agent=AgentConfig(trust="skeptic", enforce_read_before_show=False),
    )
    agent = StepAgent(llm=llm, cwd=project, config=cfg)

    async def fake_hook(_t, _o, _to):  # type: ignore[no-untyped-def]
        return "esc"

    forker = HumanForker(agent, ui_hook=fake_hook, config=cfg.agent)
    with pytest.raises(ForkError):
        await forker.resolve(
            "q",
            (ForkOption("a", "x"),),
            "ctx",
        )
