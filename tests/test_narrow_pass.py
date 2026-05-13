"""NarrowPass framework — v0.8 reliability bet.

Covers the dataclasses, run_narrow_pass override of temperature,
per_step_review skip rules and happy path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from code_scalpel.agent import StepAgent
from code_scalpel.config import AgentConfig, AppConfig, ModelProfile
from code_scalpel.narrow_pass import NarrowPass, PassResult
from code_scalpel.patch.edit_block import Edit
from code_scalpel.plan import Task
from tests.mocks import MockLLMAdapter

_CONFIG = AppConfig(
    profiles={
        "local": ModelProfile(
            provider="lmstudio",
            model="local-model",
            temperature=0.1,
        )
    },
    agent=AgentConfig(
        max_files=2,
        max_file_lines=50,
        enforce_read_before_show=False,
        per_step_review=False,
    ),
)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "hello.py").write_text("def hello():\n    return 'hi'\n")
    return tmp_path


def test_narrow_pass_is_frozen() -> None:
    """Spec is data, not state. Reviewer mutating its own prompt
    mid-run would be exactly the kind of thing this module prevents."""
    from dataclasses import FrozenInstanceError

    p = NarrowPass(name="x", system_prompt="y", temperature=0.5)
    with pytest.raises(FrozenInstanceError):
        p.temperature = 0.7  # type: ignore[misc]


def test_pass_result_carries_tokens() -> None:
    r = PassResult(name="x", text="hello", prompt_tokens=10, completion_tokens=5)
    assert r.prompt_tokens == 10
    assert r.completion_tokens == 5


@pytest.mark.asyncio
async def test_run_narrow_pass_overrides_temperature(project: Path) -> None:
    """The pass's temperature wins over the per-mode default. Reviewers
    need 0.5; the builder defaults to ~0.3 — narrow passes are
    pointless if they inherit the builder's sampling."""
    llm = MockLLMAdapter(["findings"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)
    spec = NarrowPass(name="rev", system_prompt="be skeptic", temperature=0.5)

    result = await agent.run_narrow_pass(spec, "look at this diff")

    assert result.text == "findings"
    assert llm.kwargs_calls[0]["temperature"] == 0.5


@pytest.mark.asyncio
async def test_run_narrow_pass_feeds_session(project: Path) -> None:
    """Tokens land on the attached Session so the exit summary stays
    honest — same bug G we just closed for the main loop."""
    from code_scalpel.session import Session

    session = Session()
    llm = MockLLMAdapter(["findings"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG, session=session)
    spec = NarrowPass(name="rev", system_prompt="be skeptic", temperature=0.5)

    await agent.run_narrow_pass(spec, "hello")

    assert session.requests == 1
    assert session.total_prompt_tokens > 0


@pytest.mark.asyncio
async def test_per_step_review_skips_when_no_attempts(project: Path) -> None:
    """If code_with_retry never landed an attempt (model gave up,
    plain-text answer) there's nothing to review — return None."""
    from code_scalpel.agent import StepResult
    from code_scalpel.llm.adapter import ChatResponse

    llm = MockLLMAdapter(["unused"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)
    task = Task(id="T001", title="t", body="", done=False)
    sr = StepResult(
        reply="",
        edits=[],
        response=ChatResponse(content="", prompt_tokens=0, completion_tokens=0, cost=None),
    )

    review = await agent.per_step_review(task, sr)

    assert review is None
    assert llm.calls == []  # no LLM hit


@pytest.mark.asyncio
async def test_per_step_review_runs_on_landed_diff(project: Path) -> None:
    """Happy path — task done, edits applied, tests green → reviewer
    fires with a non-empty diff message."""
    from code_scalpel.agent import PatchAttempt, StepResult
    from code_scalpel.llm.adapter import ChatResponse

    edit = Edit(path="hello.py", search="return 'hi'", replace="return 'hello'")
    attempt = PatchAttempt(
        edits=(edit,),
        apply_ok=True,
        apply_error="",
        test_output="1 passed",
        tests_passed=True,
    )
    sr = StepResult(
        reply="",
        edits=[],
        response=ChatResponse(content="", prompt_tokens=0, completion_tokens=0, cost=None),
        attempts=(attempt,),
    )
    task = Task(id="T001", title="rename greeting", body="", done=False)
    llm = MockLLMAdapter(["## Findings\n- [risk] greeting collides with i18n"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    review = await agent.per_step_review(task, sr)

    assert review is not None
    assert "[risk]" in review.text
    # Reviewer must see the diff in the user message, otherwise the
    # 14b model will hallucinate findings on a phantom file.
    user_msg = llm.calls[0][-1]["content"]
    assert "T001 — rename greeting" in user_msg
    assert "return 'hello'" in user_msg


@pytest.mark.asyncio
async def test_judge_test_sanity_returns_none_for_missing_file(project: Path) -> None:
    """Caller path: file doesn't exist → no LLM round-trip."""
    llm = MockLLMAdapter(["unused"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    result = await agent.judge_test_sanity(project / "no_such_test.py")

    assert result is None
    assert llm.calls == []


@pytest.mark.asyncio
async def test_judge_test_sanity_sends_file_content(project: Path) -> None:
    """Happy path — file content is in the user message, prompt is
    the sanity judge."""
    test_path = project / "test_hello.py"
    test_path.write_text("def test_smoke():\n    assert True\n")
    llm = MockLLMAdapter(['{"verdict":"trivial","reason":"assert True"}'])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    result = await agent.judge_test_sanity(test_path)

    assert result is not None
    assert '"trivial"' in result.text
    user_msg = llm.calls[0][-1]["content"]
    assert "assert True" in user_msg
    assert llm.kwargs_calls[0]["temperature"] == 0.0


@pytest.mark.asyncio
async def test_debug_pass_returns_structured_hint(project: Path) -> None:
    """Happy path: debug_pass returns {hypothesis, evidence,
    suggested_fix} via response_format. Caller (code_with_retry)
    splices suggested_fix into the next retry prompt."""
    payload = (
        '{"hypothesis": "ImportError: queue collides with stdlib",'
        ' "evidence": "read_file showed queue.py imports own queue",'
        ' "suggested_fix": "rename queue.py to job_queue.py"}'
    )
    llm = MockLLMAdapter([payload])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    result = await agent.debug_pass(
        task_id="T001",
        task_title="Add job queue",
        diff="queue.py\n```\n+import queue\n```",
        test_output="E   ImportError: cannot import 'enqueue' from 'queue'",
    )

    assert result is not None
    assert "ImportError" in result.text
    # Structured output schema must land in adapter kwargs.
    rf = llm.kwargs_calls[0].get("response_format")
    assert rf is not None
    assert rf["json_schema"]["name"] == "debug_pass"
    # Temperature pinned to the config knob (default 0.1).
    assert llm.kwargs_calls[0]["temperature"] == 0.1


@pytest.mark.asyncio
async def test_debug_pass_empty_test_output_is_noop(project: Path) -> None:
    """Without a failure trace there's nothing to debug. Skip the
    LLM round-trip entirely — saves tokens on the apply-failed path
    where test_output is `""`."""
    llm = MockLLMAdapter(["unused"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    result = await agent.debug_pass(
        task_id="T001",
        task_title="t",
        diff="some diff",
        test_output="",
    )

    assert result is None
    assert llm.calls == []


@pytest.mark.asyncio
async def test_debug_pass_disabled_keeps_legacy_retry_prompt(project: Path) -> None:
    """With `debug_pass=False` (default), code_with_retry falls back
    to raw _TESTS_FAILED_PROMPT. Existing /go behaviour unchanged."""
    from code_scalpel.tools.shell import ShellResult
    from tests.mocks import MockShellRunner

    bad = """\
hello.py
```python
<<<<<<< SEARCH
def hello():
    pass
=======
def hello():
    return "still wrong"
>>>>>>> REPLACE
```
"""
    llm = MockLLMAdapter([bad, bad])
    shell = MockShellRunner([ShellResult("still failing", 1)] * 3)
    cfg = AppConfig(
        profiles={"local": ModelProfile(provider="lmstudio", model="m")},
        agent=AgentConfig(
            max_files=2,
            max_file_lines=50,
            max_debug_attempts=1,
            iterative_patch_loop=True,
            enforce_read_before_show=False,
            auto_git=False,
            sandbox="off",
            debug_pass=False,  # disabled
        ),
    )
    agent = StepAgent(llm=llm, cwd=project, config=cfg, shell_runner=shell)

    await agent.code_with_retry("fix it", force_loop=True)

    # Builder ran twice (initial + 1 retry); debugger never fired.
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_debug_pass_enabled_fires_between_attempts(project: Path) -> None:
    """With debug_pass=True, a failed-test attempt routes through
    the debugger before the next builder retry. Look for the
    `debug_pass` card in the on_tool_executed stream."""
    from code_scalpel.tools.shell import ShellResult
    from tests.mocks import MockShellRunner

    # Two distinct patches so the second one's SEARCH actually
    # matches the post-first-apply state (otherwise we hit
    # apply-error path instead of tests-failed path).
    bad_one = """\
hello.py
```python
<<<<<<< SEARCH
def hello():
    return 'hi'
=======
def hello():
    return "wrong-1"
>>>>>>> REPLACE
```
"""
    bad_two = """\
hello.py
```python
<<<<<<< SEARCH
def hello():
    return "wrong-1"
=======
def hello():
    return "wrong-2"
>>>>>>> REPLACE
```
"""
    debug_payload = (
        '{"hypothesis": "wrong return value",'
        ' "evidence": "test asserts hello()==\\"hi\\"",'
        ' "suggested_fix": "return \\"hi\\" instead of \\"wrong\\""}'
    )
    llm = MockLLMAdapter([bad_one, debug_payload, bad_two])
    shell = MockShellRunner([ShellResult("first failure", 1), ShellResult("second failure", 1)])
    cfg = AppConfig(
        profiles={"local": ModelProfile(provider="lmstudio", model="m")},
        agent=AgentConfig(
            max_files=2,
            max_file_lines=50,
            max_debug_attempts=1,
            iterative_patch_loop=True,
            enforce_read_before_show=False,
            auto_git=False,
            sandbox="off",
            debug_pass=True,
            debug_pass_max_attempts=2,
        ),
    )
    agent = StepAgent(llm=llm, cwd=project, config=cfg, shell_runner=shell)
    cards: list[tuple[str, str]] = []

    def _on_tool(call, result):  # type: ignore[no-untyped-def]
        cards.append((call.name, result.output))

    await agent.code_with_retry("fix it", force_loop=True, on_tool_executed=_on_tool)

    # Builder (1) → run_tests → debug_pass → builder (2) → run_tests.
    # LLM saw 3 turns: 2 builder + 1 debug_pass.
    assert len(llm.calls) == 3
    debug_cards = [c for c in cards if c[0] == "debug_pass"]
    assert len(debug_cards) == 1
    assert "wrong return value" in debug_cards[0][1]


@pytest.mark.asyncio
async def test_debug_pass_stops_on_repeated_hypothesis(project: Path) -> None:
    """If debugger names the same hypothesis twice, that's stuck —
    break the loop instead of grinding through more attempts."""
    from code_scalpel.tools.shell import ShellResult
    from tests.mocks import MockShellRunner

    bad_one = """\
hello.py
```python
<<<<<<< SEARCH
def hello():
    return 'hi'
=======
def hello():
    return "wrong-1"
>>>>>>> REPLACE
```
"""
    bad_two = """\
hello.py
```python
<<<<<<< SEARCH
def hello():
    return "wrong-1"
=======
def hello():
    return "wrong-2"
>>>>>>> REPLACE
```
"""
    same_hypothesis = '{"hypothesis": "X is wrong", "evidence": "trace", "suggested_fix": "fix X"}'
    # builder1, debug (X), builder2, debug (X AGAIN → break), no builder3.
    llm = MockLLMAdapter([bad_one, same_hypothesis, bad_two, same_hypothesis])
    shell = MockShellRunner([ShellResult("differ A", 1), ShellResult("differ B", 1)])
    cfg = AppConfig(
        profiles={"local": ModelProfile(provider="lmstudio", model="m")},
        agent=AgentConfig(
            max_files=2,
            max_file_lines=50,
            max_debug_attempts=3,  # plenty of budget
            iterative_patch_loop=True,
            enforce_read_before_show=False,
            auto_git=False,
            sandbox="off",
            debug_pass=True,
            debug_pass_max_attempts=5,
        ),
    )
    agent = StepAgent(llm=llm, cwd=project, config=cfg, shell_runner=shell)

    await agent.code_with_retry("fix it", force_loop=True)

    # builder → debug → builder → debug (same hypothesis → break).
    # 4 LLM calls total; the 3rd builder retry never runs.
    assert len(llm.calls) == 4


@pytest.mark.asyncio
async def test_run_plan_fires_test_sanity_when_enabled(project: Path) -> None:
    """Integration: with test_sanity_pass=True, a task that modifies
    a test file triggers the sanity judge after the patch lands.
    Surfaces as a test_sanity tool card; doesn't fail the task on
    trivial verdict (strict-mode is a follow-up)."""
    from code_scalpel.tools.shell import ShellResult
    from tests.mocks import MockShellRunner

    # Project needs a test file to modify.
    (project / "test_hello.py").write_text(
        "def test_smoke():\n    from hello import hello\n    assert hello() is not None\n"
    )

    tasks_path = project / ".code-scalpel" / "TASKS.md"
    tasks_path.parent.mkdir(parents=True, exist_ok=True)
    tasks_path.write_text(
        "## T001: Tighten smoke test\n\n"
        "Goal: assert exact value\n"
        "Files: test_hello.py\n"
        "Acceptance:\n"
        "- explicit value check\n"
        "Test command: pytest\n"
    )
    patch = """\
test_hello.py
```python
<<<<<<< SEARCH
def test_smoke():
    from hello import hello
    assert hello() is not None
=======
def test_smoke():
    from hello import hello
    assert hello() == 'hi'
>>>>>>> REPLACE
```
"""
    sanity_text = '{"verdict":"meaningful","reason":"explicit value comparison"}'
    llm = MockLLMAdapter([patch, sanity_text])
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
            test_sanity_pass=True,
        ),
    )
    agent = StepAgent(llm=llm, cwd=project, config=cfg, shell_runner=shell)

    cards: list[tuple[str, str]] = []

    def _on_tool(call, result):  # type: ignore[no-untyped-def]
        cards.append((call.name, result.output))

    result = await agent.run_plan(on_tool_executed=_on_tool)

    assert result.tasks_completed == 1
    assert any(name == "test_sanity" and '"meaningful"' in out for name, out in cards)
    # Builder ran first, sanity judge second — same shape as per_step_review.
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_improve_commit_message_handles_empty_diff(project: Path) -> None:
    """Empty diff → no LLM round-trip. Saves a token-burn on the
    'I forgot to stage anything' path."""
    llm = MockLLMAdapter(["unused"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    result = await agent.improve_commit_message("")

    assert result is None
    assert llm.calls == []


@pytest.mark.asyncio
async def test_improve_commit_message_runs_with_low_temperature(project: Path) -> None:
    """Diff present → reviewer runs at temperature 0.2 (stable, not
    creative). Builder uses ~0.3; we keep close so behaviour is
    predictable across runs."""
    llm = MockLLMAdapter(["Add greeting prefix\n\nReason: align with i18n keys."])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)
    diff = "--- a/hello.py\n+++ b/hello.py\n@@\n-return 'hi'\n+return 'hello'\n"

    result = await agent.improve_commit_message(diff)

    assert result is not None
    assert "Add greeting prefix" in result.text
    assert llm.kwargs_calls[0]["temperature"] == 0.2


@pytest.mark.asyncio
async def test_improve_commit_message_truncates_huge_diff(project: Path) -> None:
    """4000-char cap protects the prompt budget from a giant rename.
    Caller still gets a result — better than refusing on size."""
    llm = MockLLMAdapter(["Rename module across project"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)
    huge = "x = 1\n" * 1000  # 6000 chars

    result = await agent.improve_commit_message(huge)

    assert result is not None
    sent = llm.calls[0][-1]["content"]
    assert len(sent) < 4500
    assert "diff truncated" in sent


@pytest.mark.asyncio
async def test_run_plan_fires_per_step_review_when_enabled(project: Path) -> None:
    """Integration: with per_step_review=True, run_plan surfaces a
    `per_step_review` tool card after the task lands. The reviewer
    is the second LLM call (first is the builder)."""
    from code_scalpel.tools.shell import ShellResult
    from tests.mocks import MockShellRunner

    tasks_path = project / ".code-scalpel" / "TASKS.md"
    tasks_path.parent.mkdir(parents=True, exist_ok=True)
    tasks_path.write_text(
        "## T001: Make hello return hello\n\n"
        "Goal: rename greeting\n"
        "Files: hello.py\n"
        "Acceptance:\n"
        "- hello() returns 'hello'\n"
        "Test command: pytest\n"
    )
    patch = """\
hello.py
```python
<<<<<<< SEARCH
def hello():
    return 'hi'
=======
def hello():
    return "hello"
>>>>>>> REPLACE
```
"""
    review_text = "## Findings\n- [risk] greeting may collide with i18n\n## Verdict\n`discuss`"
    llm = MockLLMAdapter([patch, review_text])
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
            per_step_review=True,
        ),
    )
    agent = StepAgent(llm=llm, cwd=project, config=cfg, shell_runner=shell)

    cards: list[tuple[str, str]] = []

    def _on_tool(call, result):  # type: ignore[no-untyped-def]
        cards.append((call.name, result.output))

    result = await agent.run_plan(on_tool_executed=_on_tool)

    assert result.tasks_completed == 1
    assert any(name == "per_step_review" and "[risk]" in out for name, out in cards)
    # Builder ran first, reviewer second — order matters for the user.
    assert len(llm.calls) == 2
