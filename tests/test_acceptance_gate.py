"""Tests for the run_plan acceptance gate (verification #4).

Drives the production verification entry point `plan_verify.verify_task`
(the same function `PlanRunner._run_task` calls) against a python-cli project
with a real `MockShellRunner`, so the run-smoke executes through the production
`execute()` path — no hand-rolled parallel setup. Covers the plan's Test plan:
demote / keep / no-op / timeout / pkg-unresolvable / exit-4-5 / yolo / argv /
cwd / state round-trip, plus the plan-modified interaction with the gate active.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from code_scalpel.agent import StepAgent, TaskOutcome
from code_scalpel.config import AgentConfig, AppConfig, ModelProfile
from code_scalpel.plan import Task
from code_scalpel.plan_verify import verify_task
from code_scalpel.state import AgentState
from code_scalpel.tools.shell import ShellResult
from tests.mocks import MockLLMAdapter, MockShellRunner

_SHELL_TIMEOUT = 17  # distinctive non-default value to prove config-sourcing


def _config(trust: str = "yolo") -> AppConfig:
    return AppConfig(
        profiles={"local": ModelProfile(provider="lmstudio", model="m", temperature=0.1)},
        agent=AgentConfig(
            max_files=2,
            max_file_lines=50,
            auto_git=False,
            sandbox="off",
            auto_annotate_plan=False,
            shell_exec_timeout=_SHELL_TIMEOUT,
            trust=trust,
        ),
    )


def _python_cli_project(tmp_path: Path, pkg: str = "notes_cli") -> Path:
    pkg_dir = tmp_path / "src" / pkg
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "__init__.py").write_text("")
    (pkg_dir / "__main__.py").write_text("")
    (tmp_path / "pyproject.toml").write_text(
        "[build-system]\nrequires=['hatchling']\nbuild-backend='hatchling.build'\n"
        "[project]\nname='x'\nversion='0'\n"
        f"[tool.hatch.build.targets.wheel]\npackages=['src/{pkg}']\n"
    )
    return tmp_path


def _agent(
    project: Path,
    shell: MockShellRunner,
    *,
    trust: str = "yolo",
    state: AgentState | None = None,
) -> StepAgent:
    return StepAgent(
        llm=MockLLMAdapter(["x"]),
        cwd=project,
        config=_config(trust),
        shell_runner=shell,
        state=state,
    )


def _done(task: Task) -> TaskOutcome:
    from code_scalpel.agent import StepResult

    sr = StepResult(reply="ok", edits=[], response=None)  # type: ignore[arg-type]
    return TaskOutcome(task=task, step_result=sr, status="done")


# Task with no `Files:` / `Test command:` declarations — so checks 1-2 are
# no-ops and the test isolates verification #4 (the acceptance gate).
_TASK = Task(id="T001", title="ship cli", body="Goal: ship the cli\n", done=False)


@pytest.mark.asyncio
async def test_acceptance_gate_keeps_done_when_runsmoke_succeeds(tmp_path: Path) -> None:
    project = _python_cli_project(tmp_path)
    shell = MockShellRunner([ShellResult("usage: notes_cli", 0)])
    out = await verify_task(_agent(project, shell), _TASK, _done(_TASK), head_before=None)
    assert out.status == "done"


@pytest.mark.asyncio
async def test_acceptance_gate_demotes_done_to_failed_when_runsmoke_fails(tmp_path: Path) -> None:
    project = _python_cli_project(tmp_path)
    shell = MockShellRunner([ShellResult("Traceback ... not runnable", 1)])
    outcome = _done(_TASK)
    out = await verify_task(_agent(project, shell), _TASK, outcome, head_before=None)
    assert out.status == "failed"
    # Partial progress preserved — the same task/step_result, just demoted.
    assert out.task is _TASK
    assert out.step_result is outcome.step_result


@pytest.mark.asyncio
async def test_acceptance_gate_noop_when_no_acceptance_adapter(tmp_path: Path) -> None:
    """A project with no provides_acceptance adapter → gate is a no-op; the
    done verdict from checks 1-3 stands (no regression for unsupported types)."""
    (tmp_path / "go.mod").write_text("module x\n")  # Go: no acceptance adapter
    shell = MockShellRunner([])
    state = AgentState()
    out = await verify_task(_agent(tmp_path, shell, state=state), _TASK, _done(_TASK), None)
    assert out.status == "done"
    # No run-smoke was dispatched.
    assert shell.shell_calls == []
    assert state.last_acceptance_verdict == "noop"


@pytest.mark.asyncio
async def test_acceptance_pkg_unresolvable_fails(tmp_path: Path) -> None:
    """A python project that detects (pyproject present) but produces no
    -m-runnable package → resolve_pkg raises → failed, reason pkg-unresolvable."""
    # pyproject with no wheel target and no src/ package — resolve_pkg raises.
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    shell = MockShellRunner([])
    state = AgentState()
    out = await verify_task(_agent(tmp_path, shell, state=state), _TASK, _done(_TASK), None)
    assert out.status == "failed"
    assert state.last_acceptance_reason == "pkg-unresolvable"
    # The unresolvable failure is detected without ever dispatching a shell.
    assert shell.shell_calls == []


@pytest.mark.asyncio
async def test_acceptance_runsmoke_timeout_fails(tmp_path: Path) -> None:
    """A run-smoke that times out → failed; the timeout reason is recorded.

    The MockShellRunner returns the execute() path's timeout shape; the
    timeout value itself comes from config (_SHELL_TIMEOUT), asserted in
    test_acceptance_runsmoke_uses_config_timeout — not a literal here."""
    project = _python_cli_project(tmp_path)

    class _TimeoutRunner(MockShellRunner):
        async def run_shell(self, command: str, cwd: str | None = None, timeout: int = 30):
            self.shell_calls.append(command)
            raise TimeoutError

    shell = _TimeoutRunner([])
    state = AgentState()
    out = await verify_task(_agent(project, shell, state=state), _TASK, _done(_TASK), None)
    assert out.status == "failed"
    assert state.last_acceptance_reason == "timeout"


@pytest.mark.asyncio
async def test_acceptance_runsmoke_uses_config_timeout(tmp_path: Path) -> None:
    """run-smoke is dispatched with the configured shell_exec_timeout — proves
    the timeout is config-sourced, not a magic number (scenario 7)."""
    project = _python_cli_project(tmp_path)
    seen: list[int] = []

    class _CaptureRunner(MockShellRunner):
        async def run_shell(self, command: str, cwd: str | None = None, timeout: int = 30):
            seen.append(timeout)
            return ShellResult("ok", 0)

    shell = _CaptureRunner([])
    await verify_task(_agent(project, shell), _TASK, _done(_TASK), None)
    assert seen == [_SHELL_TIMEOUT]


@pytest.mark.asyncio
async def test_acceptance_does_not_inherit_exit_4_5_leniency(tmp_path: Path) -> None:
    """run-smoke is exit-0-or-fail: exit 4 and exit 5 are FAILURES, unlike
    _verify_task_test_command which treats them as pass (arch-note sharpening)."""
    project = _python_cli_project(tmp_path)
    for code in (4, 5):
        shell = MockShellRunner([ShellResult("no tests ran", code)])
        out = await verify_task(_agent(project, shell), _TASK, _done(_TASK), None)
        assert out.status == "failed", f"exit {code} must fail run-smoke"


@pytest.mark.asyncio
async def test_runsmoke_executed_via_yolo_plan_owned_path(tmp_path: Path) -> None:
    """On a skeptic-trust project the run-smoke still executes (plan-owned,
    trust=yolo) without a confirmation handler — mirroring test-command
    verification. A skeptic-gated shell_exec without a confirm would refuse."""
    project = _python_cli_project(tmp_path)
    shell = MockShellRunner([ShellResult("usage", 0)])
    # trust=skeptic on the agent; the gate must run-smoke at yolo regardless.
    out = await verify_task(_agent(project, shell, trust="skeptic"), _TASK, _done(_TASK), None)
    assert out.status == "done"
    assert shell.shell_calls == ["python -m notes_cli --help"]


@pytest.mark.asyncio
async def test_runsmoke_command_is_code_owned_argv(tmp_path: Path) -> None:
    """The executed command equals the adapter's code-owned argv joined —
    `python -m <pkg> --help`, not model- or user-supplied text."""
    project = _python_cli_project(tmp_path, pkg="notes_cli")
    shell = MockShellRunner([ShellResult("usage", 0)])
    await verify_task(_agent(project, shell), _TASK, _done(_TASK), None)
    assert shell.shell_calls == ["python -m notes_cli --help"]


@pytest.mark.asyncio
async def test_runsmoke_uses_argv_no_shell(tmp_path: Path) -> None:
    """The acceptance execution is built from an argv list (the adapter's
    code-owned command), not free-form text: shlex round-trips it cleanly
    with no shell metacharacters, so no untrusted string reaches a shell.

    Cites asyncio-subprocess security considerations — never pass untrusted
    input to a shell:
    https://docs.python.org/3/library/asyncio-subprocess.html#security-considerations
    """
    import shlex

    project = _python_cli_project(tmp_path)
    shell = MockShellRunner([ShellResult("usage", 0)])
    await verify_task(_agent(project, shell), _TASK, _done(_TASK), None)
    command = shell.shell_calls[0]
    argv = shlex.split(command)
    # The command IS the argv joined — a clean code-owned argv with no shell
    # operators (|, &&, ;, >, $()).
    assert argv == ["python", "-m", "notes_cli", "--help"]
    assert shlex.join(argv) == command
    assert not any(tok in command for tok in ("|", "&&", ";", ">", "$(", "`"))


@pytest.mark.asyncio
async def test_runsmoke_cwd_pinned_to_root(tmp_path: Path) -> None:
    """The run-smoke subprocess cwd is the project root (stack-notes SC2:
    subprocess cwd is pinned to the project root)."""
    project = _python_cli_project(tmp_path)
    seen: list[str | None] = []

    class _CwdRunner(MockShellRunner):
        async def run_shell(self, command: str, cwd: str | None = None, timeout: int = 30):
            seen.append(cwd)
            return ShellResult("ok", 0)

    shell = _CwdRunner([])
    await verify_task(_agent(project, shell), _TASK, _done(_TASK), None)
    assert seen == [str(project)]


@pytest.mark.asyncio
async def test_state_persists_runsmoke_verdict_and_reason(tmp_path: Path) -> None:
    """AgentState round-trips the new run-smoke command/verdict/reason fields;
    an old STATE.json without them still loads (forward-compatible defaults)."""
    project = _python_cli_project(tmp_path)
    shell = MockShellRunner([ShellResult("boom", 2)])
    state = AgentState()
    await verify_task(_agent(project, shell, state=state), _TASK, _done(_TASK), None)
    assert state.last_acceptance_command == "python -m notes_cli --help"
    assert state.last_acceptance_verdict == "failed"
    assert state.last_acceptance_reason == "exit 2"

    # Persisted + reloaded round-trips.
    state.save(project)
    reloaded = AgentState.load(project)
    assert reloaded.last_acceptance_verdict == "failed"
    assert reloaded.last_acceptance_reason == "exit 2"

    # An old STATE.json missing the new keys still loads with defaults.
    legacy = '{"current_task": null, "completed_tasks": []}'
    (project / ".code-scalpel").mkdir(exist_ok=True)
    (project / ".code-scalpel" / "STATE.json").write_text(legacy)
    old = AgentState.load(project)
    assert old.last_acceptance_verdict == "unknown"
    assert old.last_acceptance_command is None


@pytest.mark.asyncio
async def test_done_count_means_ran(tmp_path: Path) -> None:
    """The Must-not-break contract: a task that stays `done` through the gate
    has a recorded `passed` run-smoke verdict — `done` now means `ran`."""
    project = _python_cli_project(tmp_path)
    shell = MockShellRunner([ShellResult("usage", 0)])
    state = AgentState()
    out = await verify_task(_agent(project, shell, state=state), _TASK, _done(_TASK), None)
    assert out.status == "done"
    assert state.last_acceptance_verdict == "passed"


@pytest.mark.asyncio
async def test_acceptance_card_surfaced(tmp_path: Path) -> None:
    """The acceptance step rides the existing on_tool_executed card seam so the
    user sees the command + ✓/✗."""
    project = _python_cli_project(tmp_path)
    shell = MockShellRunner([ShellResult("usage", 0)])
    cards: list[tuple[str, bool]] = []

    def _on_tool(call, result) -> None:  # type: ignore[no-untyped-def]
        cards.append((call.name, result.ok))

    await verify_task(_agent(project, shell), _TASK, _done(_TASK), None, _on_tool)
    assert ("acceptance", True) in cards
