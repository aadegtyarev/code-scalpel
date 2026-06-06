"""Tests for the run_plan acceptance gate (verification #4).

Drives the production verification entry point `plan_verify.verify_task`
(the same function `PlanRunner._run_task` calls) against a python-cli project
with a real `MockShellRunner`, so the run-smoke executes through the production
`execute()` path — no hand-rolled parallel setup.

`feat/acceptance-spec-in-tasks` flips verification #4 from observational-only
to ENFORCING where an *applicable* spec exists. The tasks here carry no declared
acceptance, so the adapter returns the default-floor (`applicable=False`) — these
tests therefore still assert "recorded, NOT demoted" (the no-regression branch:
a project with no applicable spec — a library — is never wrongly failed). The
demoting branch (an applicable declared/derived spec that fails) is covered in
`test_acceptance_enforcement.py`. Covers the plan's Test plan:
record-passed / record-failed-but-keep-done / no-op / library-not-demoted /
timeout / pkg-unresolvable / exit-4-5 / expected-observable / yolo / argv /
cwd / state round-trip / noop-no-clobber, plus the plan-modified interaction.
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
async def test_acceptance_records_failed_but_does_NOT_demote_when_runsmoke_fails(
    tmp_path: Path,
) -> None:
    """Plumbing only: a non-zero run-smoke is recorded `failed` + surfaced but
    the task STAYS `done` (observational — the load-bearing no-regression guard
    for the PM "plumbing only" decision; scenario 2)."""
    project = _python_cli_project(tmp_path)
    shell = MockShellRunner([ShellResult("Traceback ... not runnable", 1)])
    outcome = _done(_TASK)
    state = AgentState()
    out = await verify_task(_agent(project, shell, state=state), _TASK, outcome, head_before=None)
    # Verdict recorded as failed, but the task is NOT demoted.
    assert out.status == "done"
    assert out.task is _TASK
    assert out.step_result is outcome.step_result
    assert state.last_acceptance_verdict == "failed"
    assert state.last_acceptance_reason == "exit 1"


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
async def test_acceptance_pkg_unresolvable_records_reason(tmp_path: Path) -> None:
    """A python project that detects (pyproject present) but produces no
    -m-runnable package → resolve_pkg raises → verdict `failed`, reason
    `pkg-unresolvable`, NO new status, and the task is NOT demoted (scenario 8,
    plumbing only)."""
    # pyproject with no wheel target and no src/ package — resolve_pkg raises.
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    shell = MockShellRunner([])
    state = AgentState()
    out = await verify_task(_agent(tmp_path, shell, state=state), _TASK, _done(_TASK), None)
    assert out.status == "done"
    assert state.last_acceptance_verdict == "failed"
    assert state.last_acceptance_reason == "pkg-unresolvable"
    # The unresolvable failure is detected without ever dispatching a shell.
    assert shell.shell_calls == []


@pytest.mark.asyncio
async def test_acceptance_library_project_not_demoted(tmp_path: Path) -> None:
    """A python LIBRARY (no CLI) must NOT be demoted — the exact regression the
    plumbing-only scope prevents. Two layouts: a src-layout single package with
    no `__main__.py` (run-smoke fails non-zero) and a flat-layout library
    (`resolve_pkg` raises → pkg-unresolvable). Both record `failed` and stay
    `done`. (`PythonCliAdapter.detect` fires on ANY python project, so without
    feature 4's CLI-intent signal a demoting gate would wrongly fail these.)"""
    # 1) src-layout library: a package, but no __main__.py — `python -m mylib`
    #    fails. run-smoke returns non-zero; recorded failed, task stays done.
    src_lib = tmp_path / "srclib"
    pkg_dir = src_lib / "src" / "mylib"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "__init__.py").write_text("")
    (src_lib / "pyproject.toml").write_text(
        "[build-system]\nrequires=['hatchling']\nbuild-backend='hatchling.build'\n"
        "[project]\nname='mylib'\nversion='0'\n"
        "[tool.hatch.build.targets.wheel]\npackages=['src/mylib']\n"
    )
    shell = MockShellRunner([ShellResult("No module named mylib.__main__", 1)])
    state = AgentState()
    out = await verify_task(_agent(src_lib, shell, state=state), _TASK, _done(_TASK), None)
    assert out.status == "done", "src-layout library must NOT be demoted"
    assert state.last_acceptance_verdict == "failed"

    # 2) flat-layout library: pyproject with no wheel target / no src package —
    #    resolve_pkg raises → pkg-unresolvable, recorded, task stays done.
    flat_lib = tmp_path / "flatlib"
    flat_lib.mkdir()
    (flat_lib / "pyproject.toml").write_text("[project]\nname='flat'\n")
    flat_shell = MockShellRunner([])
    flat_state = AgentState()
    out2 = await verify_task(
        _agent(flat_lib, flat_shell, state=flat_state), _TASK, _done(_TASK), None
    )
    assert out2.status == "done", "flat-layout library must NOT be demoted"
    assert flat_state.last_acceptance_verdict == "failed"
    assert flat_state.last_acceptance_reason == "pkg-unresolvable"
    assert flat_shell.shell_calls == []


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
    # Recorded failed (reason timeout), task NOT demoted (plumbing only).
    assert out.status == "done"
    assert state.last_acceptance_verdict == "failed"
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
    """run-smoke is exit-0-or-fail: exit 4 and exit 5 are recorded FAILED,
    unlike _verify_task_test_command which treats them as pass (arch-note
    sharpening). Plumbing only — the task is not demoted, but the recorded
    verdict is `failed`, not `passed`."""
    project = _python_cli_project(tmp_path)
    for code in (4, 5):
        shell = MockShellRunner([ShellResult("no tests ran", code)])
        state = AgentState()
        out = await verify_task(_agent(project, shell, state=state), _TASK, _done(_TASK), None)
        assert out.status == "done", f"plumbing only: exit {code} must not demote"
        assert state.last_acceptance_verdict == "failed", f"exit {code} must record failed"


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
async def test_acceptance_records_passed_when_runsmoke_succeeds(tmp_path: Path) -> None:
    """Scenario 1: a task whose `python -m <pkg> --help` exits 0 has its verdict
    recorded `passed` and stays `done`. (Plumbing only: the passed verdict is
    observability, not the demotion driver.)"""
    project = _python_cli_project(tmp_path)
    shell = MockShellRunner([ShellResult("usage", 0)])
    state = AgentState()
    out = await verify_task(_agent(project, shell, state=state), _TASK, _done(_TASK), None)
    assert out.status == "done"
    assert state.last_acceptance_verdict == "passed"


@pytest.mark.asyncio
async def test_acceptance_expected_observable_checked_when_nonempty(tmp_path: Path) -> None:
    """Finding 2: when an adapter returns a non-empty `expected`, a run-smoke
    that exits 0 but whose output lacks `expected` is recorded `failed`
    (guards the false-green); the floor (`expected == ""`) is exit-0-only."""
    project = _python_cli_project(tmp_path)
    shell = MockShellRunner([ShellResult("nothing useful printed", 0)])
    state = AgentState()

    from code_scalpel.skills.base import AcceptanceSpec

    class _ExpectingAdapter:
        def acceptance_spec(self, task: object) -> AcceptanceSpec:
            # applicable=False keeps this an OBSERVATIONAL test of the
            # expected-observable check (the demotion gate is tested
            # separately); the verdict is recorded but the task is not demoted.
            return AcceptanceSpec(
                command="python -m notes_cli --help",
                expected="usage:",
                applicable=False,
                source="floor",
            )

    agent = _agent(project, shell, state=state)
    import code_scalpel.plan_verify as pv

    # Patch the registry resolution to hand back an adapter with a non-empty
    # expected observable; the floor adapter returns expected == "".
    orig = pv.acceptance_adapter
    pv.acceptance_adapter = lambda root: _ExpectingAdapter()  # type: ignore[assignment]
    try:
        out = await verify_task(agent, _TASK, _done(_TASK), None)
    finally:
        pv.acceptance_adapter = orig  # type: ignore[assignment]
    # Exit 0 but `usage:` absent from output → recorded failed (not demoted).
    assert out.status == "done"
    assert state.last_acceptance_verdict == "failed"
    assert state.last_acceptance_reason == "expected-missing"

    # And when the expected observable IS present, the verdict is passed.
    shell2 = MockShellRunner([ShellResult("usage: notes_cli [--help]", 0)])
    state2 = AgentState()
    agent2 = _agent(project, shell2, state=state2)
    pv.acceptance_adapter = lambda root: _ExpectingAdapter()  # type: ignore[assignment]
    try:
        await verify_task(agent2, _TASK, _done(_TASK), None)
    finally:
        pv.acceptance_adapter = orig  # type: ignore[assignment]
    assert state2.last_acceptance_verdict == "passed"


@pytest.mark.asyncio
async def test_noop_does_not_clobber_prior_verdict_or_persist(tmp_path: Path) -> None:
    """Finding 3: a later `noop` task does not overwrite an earlier
    `passed`/`failed` verdict and does not trigger a redundant state write."""
    # A python-cli project (adapter resolves) → a real verdict first.
    project = _python_cli_project(tmp_path)
    shell = MockShellRunner([ShellResult("usage", 0)])
    state = AgentState()
    agent = _agent(project, shell, state=state)
    await verify_task(agent, _TASK, _done(_TASK), None)
    assert state.last_acceptance_verdict == "passed"

    # Count persist calls across the next (noop) verification.
    persist_calls = {"n": 0}
    orig_persist = agent._persist_state

    def _counting_persist() -> None:
        persist_calls["n"] += 1
        orig_persist()

    agent._persist_state = _counting_persist  # type: ignore[method-assign]

    # Force a noop by resolving no acceptance adapter for this call.
    import code_scalpel.plan_verify as pv

    orig = pv.acceptance_adapter
    pv.acceptance_adapter = lambda root: None  # type: ignore[assignment]
    try:
        await verify_task(agent, _TASK, _done(_TASK), None)
    finally:
        pv.acceptance_adapter = orig  # type: ignore[assignment]

    # The prior `passed` verdict survives the noop, and no redundant write fired.
    assert state.last_acceptance_verdict == "passed"
    assert persist_calls["n"] == 0


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
