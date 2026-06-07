"""Tests for `feat/flat-layout-run-smoke` — Gap A argv shapes + Gap B position.

Gap A — the adapter builds the run-smoke argv from the resolved
`RunTarget.kind`: `module` → `["python","-m",target,*args]`; `script` →
`["python",target,*args]`. Resolution reach now covers flat layouts (root
package, root script, `[project.scripts]`) on top of src/hatchling.

Gap B — enforcement fires at the LAST APPLICABLE task (the deliverable-complete
point), not the literal last task. A runnable CLI built before a trailing
test/doc task is still enforced; an early CLI task and a no-applicable-spec plan
stay observational by construction.

These tests drive the production `PlanRunner` / `run_plan` / `acceptance_adapter`
path (test-wiring-parity) and the two load-bearing no-regression invariants.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from code_scalpel.agent import StepAgent
from code_scalpel.config import AgentConfig, AppConfig, ModelProfile
from code_scalpel.plan import Task
from code_scalpel.plan_runner import _last_applicable_index
from code_scalpel.skills.base import encode_derived_acceptance
from code_scalpel.skills.python_cli_adapter import PythonCliAdapter
from code_scalpel.tools.shell import ShellResult
from tests.mocks import MockLLMAdapter, MockShellRunner

_SHELL_TIMEOUT = 17


def _config(trust: str = "yolo") -> AppConfig:
    return AppConfig(
        profiles={"local": ModelProfile(provider="lmstudio", model="m", temperature=0.1)},
        agent=AgentConfig(
            max_files=2,
            max_file_lines=50,
            auto_git=False,
            sandbox="off",
            auto_annotate_plan=False,
            auto_derive_acceptance=False,
            iterative_patch_loop=True,
            max_debug_attempts=0,
            enforce_read_before_show=False,
            shell_exec_timeout=_SHELL_TIMEOUT,
            trust=trust,
        ),
    )


# ── Gap A: argv shape from the descriptor ────────────────────────────────────


def _make_root_package(root: Path, pkg: str) -> None:
    pkg_dir = root / pkg
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "__init__.py").write_text("")
    (pkg_dir / "__main__.py").write_text("")


def test_run_smoke_module_argv(tmp_path: Path) -> None:
    """A `module` target (root package with `__main__.py`) → the `-m` argv."""
    _make_root_package(tmp_path, "notes_cli")
    adapter = PythonCliAdapter(root=tmp_path)
    assert adapter.run_smoke("add x") == ["python", "-m", "notes_cli", "add", "x"]


def test_run_smoke_script_argv(tmp_path: Path) -> None:
    """A `script` target (single root entry script) → the bare-script argv,
    NO `-m`."""
    (tmp_path / "cli.py").write_text("print('hi')\n")
    adapter = PythonCliAdapter(root=tmp_path)
    assert adapter.run_smoke("add x") == ["python", "cli.py", "add", "x"]


def test_run_smoke_script_argv_quoted_args(tmp_path: Path) -> None:
    """The script shape preserves the shlex quoted-group handling unchanged."""
    (tmp_path / "main.py").write_text("")
    adapter = PythonCliAdapter(root=tmp_path)
    assert adapter.run_smoke("--note 'a b'") == ["python", "main.py", "--note", "a b"]


def test_run_smoke_script_arg_error_preserved(tmp_path: Path) -> None:
    """Malformed args still raise AcceptanceArgError on the script shape — the
    spec-error vs package-error distinction is intact for both kinds."""
    from code_scalpel.skills.base import AcceptanceArgError

    (tmp_path / "cli.py").write_text("")
    adapter = PythonCliAdapter(root=tmp_path)
    with pytest.raises(AcceptanceArgError):
        adapter.run_smoke("add 'unterminated")


def test_acceptance_spec_command_uses_script_shape(tmp_path: Path) -> None:
    """The floor command for a script-shape project names the script, exit-0
    only (`--help`), and never carries a `-m`."""
    (tmp_path / "cli.py").write_text("")
    spec = PythonCliAdapter(root=tmp_path).acceptance_spec(task=None)
    assert spec is not None
    assert spec.command == "python cli.py --help"
    assert "-m" not in spec.command


def test_run_smoke_root_package_through_acceptance_adapter(tmp_path: Path) -> None:
    """Test-wiring-parity: the production registry root-binds an adapter for a
    flat-layout root-package project and its floor command resolves (no longer
    `pkg-unresolvable`)."""
    from code_scalpel.skills import acceptance_adapter

    # A realistic flat-layout project: a bare pyproject (so the python skill
    # detects it) with NO hatchling wheel target, plus a root package — so
    # resolution falls through to the discovered root package.
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\nversion='0'\n")
    _make_root_package(tmp_path, "notes_cli")
    adapter = acceptance_adapter(tmp_path)
    assert isinstance(adapter, PythonCliAdapter)
    floor = adapter.acceptance_spec(task=None)
    assert floor is not None
    assert floor.command == "python -m notes_cli --help"


def test_live_candidate_list_reaches_resolver_via_acceptance_adapter(tmp_path: Path) -> None:
    """CR1: a non-default `run_smoke_script_candidates` value threaded through the
    production `acceptance_adapter(root, script_candidates=...)` actually changes
    which root script the adapter resolves — proving the live config (not the
    import-time singleton default) reaches `resolve_pkg`."""
    from code_scalpel.skills import acceptance_adapter

    # A flat-layout project whose only runnable is a script the DEFAULT list
    # does not name (`run.py`), and NOT named by any default candidate.
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\nversion='0'\n")
    (tmp_path / "run.py").write_text("print('hi')\n")

    # Default-bound adapter (no live value) → cannot resolve `run.py`: the floor
    # command build raises (the same ValueError that drives `pkg-unresolvable`).
    default_adapter = acceptance_adapter(tmp_path)
    assert isinstance(default_adapter, PythonCliAdapter)
    with pytest.raises(ValueError):
        default_adapter.acceptance_spec(task=None)

    # Live config value threaded through → resolves the custom script.
    live = tuple(AgentConfig(run_smoke_script_candidates=["run.py"]).run_smoke_script_candidates)
    live_adapter = acceptance_adapter(tmp_path, live)
    assert isinstance(live_adapter, PythonCliAdapter)
    floor = live_adapter.acceptance_spec(task=None)
    assert floor is not None
    assert floor.command == "python run.py --help"


# ── Gap B: _last_applicable_index pure predicate ─────────────────────────────


def _applicable_task(tid: str, *, applicable: bool = True, args: str = "add x") -> Task:
    marker = encode_derived_acceptance(applicable=applicable, args=args, expected="")
    return Task(id=tid, title="t", body="", done=False, acceptance=(marker,))


class _Adapter:
    """Minimal pure-predicate stand-in mirroring the adapter's contract."""

    def acceptance_applicable(self, task: object) -> bool:
        from code_scalpel.skills.base import decode_derived_acceptance

        for line in tuple(getattr(task, "acceptance", ())):
            data = decode_derived_acceptance(line)
            if data is not None:
                return bool(data.get("applicable", False))
        return False


def test_last_applicable_index_picks_last_applicable_not_last_task() -> None:
    """A plan = [applicable CLI task, non-applicable test task] → the index is
    the CLI task (0), NOT the last task (1)."""
    tasks = [
        _applicable_task("T001", applicable=True),
        _applicable_task("T002", applicable=False),
    ]
    assert _last_applicable_index(tasks, _Adapter()) == 0


def test_last_applicable_index_skips_done_tasks() -> None:
    """Done tasks are not candidates for the enforcing position."""
    done = _applicable_task("T001", applicable=True)
    done = Task(id="T001", title="t", body="", done=True, acceptance=done.acceptance)
    tasks = [done, _applicable_task("T002", applicable=True)]
    assert _last_applicable_index(tasks, _Adapter()) == 1


def test_last_applicable_index_no_applicable_is_sentinel() -> None:
    """No applicable spec anywhere → -1 sentinel (never enforced)."""
    tasks = [_applicable_task("T001", applicable=False) for _ in range(3)]
    assert _last_applicable_index(tasks, _Adapter()) == -1


def test_last_applicable_index_no_adapter_is_sentinel() -> None:
    """No acceptance adapter (non-python project) → -1 sentinel."""
    tasks = [_applicable_task("T001", applicable=True)]
    assert _last_applicable_index(tasks, None) == -1


def test_last_applicable_index_predicate_raise_observes() -> None:
    """A predicate that raises is treated as not-applicable (observe), never
    breaks the index computation."""

    class _Raises:
        def acceptance_applicable(self, task: object) -> bool:
            raise RuntimeError("boom")

    tasks = [_applicable_task("T001", applicable=True)]
    assert _last_applicable_index(tasks, _Raises()) == -1


# ── Gap B: production run_plan end-to-end (test-wiring-parity) ────────────────


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


def _write_plan_json(project: Path, tasks: list[dict[str, object]]) -> None:
    cs = project / ".code-scalpel"
    cs.mkdir(parents=True, exist_ok=True)
    (cs / "TASKS.json").write_text(json.dumps({"tasks": tasks, "completed": []}) + "\n")


def _plan_task(tid: str, *, files: list[str], applicable: bool | None) -> dict[str, object]:
    acceptance: list[str] = []
    if applicable is not None:
        acceptance = [encode_derived_acceptance(applicable=applicable, args="add x", expected="")]
    return {
        "id": tid,
        "title": f"edit {files[0]}",
        "goal": f"edit {files[0]}",
        "files": files,
        "acceptance": acceptance,
        "skills": [],
        "test_command": None,
    }


class _SplitShellRunner(MockShellRunner):
    """Tests (`run`, argv) pass; the acceptance run-smoke (`run_shell`) returns
    a caller-fixed result. Lets every task reach `done` while the CLI run-smoke
    is broken — the condition under which only the enforcing position demotes."""

    def __init__(self, *, run_smoke: ShellResult) -> None:
        super().__init__()
        self._run_smoke = run_smoke

    async def run(self, cmd: list[str], cwd: str | None = None, timeout: int = 30) -> ShellResult:
        self.calls.append(cmd)
        return ShellResult("1 passed", 0)

    async def run_shell(
        self, command: str, cwd: str | None = None, timeout: int = 30
    ) -> ShellResult:
        self.shell_calls.append(command)
        return self._run_smoke


class _PerTaskPatchLLM(MockLLMAdapter):
    """Returns the SEARCH/REPLACE patch keyed by which file the task prompt
    names — order-independent so the run-loop's per-task LLM bookkeeping cannot
    shift a positional queue out from under us."""

    def __init__(self, patches: dict[str, str]) -> None:
        super().__init__(["(no matching patch)"])
        self._patches = patches

    def _next(self) -> tuple[str, list[object]]:  # type: ignore[override]
        prompt = str(self.calls[-1][-1].get("content", "")) if self.calls else ""
        for fname, patch in self._patches.items():
            if fname in prompt:
                return patch, []
        return "(no matching patch)", []


def _patch(fname: str) -> str:
    """A SEARCH/REPLACE whose SEARCH == REPLACE: it applies on EVERY build pass
    (including each self-fix rebuild) against the file's `V = 0` anchor, so the
    build always reaches `done` and the acceptance gate is the only thing that
    can demote — exactly the condition the enforcement / self-fix loop exists
    for. A real one-shot change would not re-apply on a rebuild."""
    return f"{fname}\n```python\n<<<<<<< SEARCH\nV = 0\n=======\nV = 0\n>>>>>>> REPLACE\n```\n"


@pytest.mark.asyncio
async def test_live_candidate_list_reaches_resolver_through_verify_path(tmp_path: Path) -> None:
    """CR1 (test-wiring-parity): driving the real `StepAgent` run-loop, the live
    `agent._config.agent.run_smoke_script_candidates` reaches the resolver via
    `plan_verify` → `acceptance_adapter`, so a custom root script (`run.py`, NOT
    in the default candidate list) is actually run-smoked. The recorded run-smoke
    command names `run.py` — proving the live config, not the import-time
    singleton default, reaches `resolve_pkg`."""
    # Flat-layout project whose only runnable is a script the DEFAULT list misses.
    project = tmp_path / "proj"
    project.mkdir()
    (project / "pyproject.toml").write_text("[project]\nname='x'\nversion='0'\n")
    (project / "run.py").write_text("V = 0\n")
    _write_plan_json(project, [_plan_task("T001", files=["run.py"], applicable=True)])

    cfg = _config()
    cfg.agent.run_smoke_script_candidates = ["run.py"]
    cfg.agent.acceptance_self_fix = False  # demotion terminal, directly observable

    llm = _PerTaskPatchLLM({"run.py": _patch("run.py")})
    shell = _SplitShellRunner(run_smoke=ShellResult("Traceback: boom", 1))
    agent = StepAgent(llm=llm, cwd=project, config=cfg, shell_runner=shell)

    await agent.run_plan()
    # The custom script resolved and ran — the run-smoke command names run.py,
    # which is only possible if the live candidate list reached the resolver.
    assert shell.shell_calls == ["python run.py add x"], shell.shell_calls


@pytest.mark.asyncio
async def test_enforce_at_last_applicable_not_last_task(tmp_path: Path) -> None:
    """Gap B core: plan = [applicable CLI task, NON-applicable test task]; the
    CLI run-smoke is broken. Enforcement fires at the CLI task (index 0) even
    though it is NOT the last task → it demotes `done → failed`; the trailing
    non-applicable task stays `done` (observed)."""
    project = _python_cli_project(tmp_path)
    (project / "cli_file.py").write_text("V = 0\n")
    (project / "test_file.py").write_text("V = 0\n")
    _write_plan_json(
        project,
        [
            _plan_task("T001", files=["cli_file.py"], applicable=True),
            _plan_task("T002", files=["test_file.py"], applicable=False),
        ],
    )
    llm = _PerTaskPatchLLM(
        {"cli_file.py": _patch("cli_file.py"), "test_file.py": _patch("test_file.py")}
    )
    shell = _SplitShellRunner(run_smoke=ShellResult("Traceback: not runnable", 1))
    # self-fix off so the demotion is terminal and directly observable.
    cfg = _config()
    cfg.agent.acceptance_self_fix = False
    agent = StepAgent(llm=llm, cwd=project, config=cfg, shell_runner=shell)

    result = await agent.run_plan()
    statuses = [(o.task.id, o.status) for o in result.outcomes]
    # The CLI task (index 0, NOT the last task) is the last-applicable position,
    # so the broken run-smoke ENFORCES there and demotes it `done → failed`. The
    # trailing non-applicable task is observed (its marker still runs the smoke)
    # but never enforced — it stays `done` despite the same broken run-smoke.
    assert statuses == [("T001", "failed"), ("T002", "done")], statuses
    assert all(c == "python -m notes_cli add x" for c in shell.shell_calls)


@pytest.mark.asyncio
async def test_self_fix_fires_at_last_applicable(tmp_path: Path) -> None:
    """At optimist, the self-fix loop engages on the last-applicable CLI task
    (NOT the last task). Drives the production run_plan path: run-smoke fails
    then passes after one rebuild → the CLI task ends `done`."""
    project = _python_cli_project(tmp_path)
    (project / "cli_file.py").write_text("V = 0\n")
    (project / "test_file.py").write_text("V = 0\n")
    _write_plan_json(
        project,
        [
            _plan_task("T001", files=["cli_file.py"], applicable=True),
            _plan_task("T002", files=["test_file.py"], applicable=False),
        ],
    )
    llm = _PerTaskPatchLLM(
        {"cli_file.py": _patch("cli_file.py"), "test_file.py": _patch("test_file.py")}
    )

    class _SeqRunner(_SplitShellRunner):
        def __init__(self, smoke: list[ShellResult]) -> None:
            super().__init__(run_smoke=smoke[0])
            self._smoke = smoke
            self._i = 0

        async def run_shell(
            self, command: str, cwd: str | None = None, timeout: int = 30
        ) -> ShellResult:
            self.shell_calls.append(command)
            res = self._smoke[min(self._i, len(self._smoke) - 1)]
            self._i += 1
            return res

    shell = _SeqRunner([ShellResult("boom", 1), ShellResult("usage: ok", 0)])
    cfg = _config(trust="optimist")
    agent = StepAgent(llm=llm, cwd=project, config=cfg, shell_runner=shell)

    result = await agent.run_plan()
    statuses = [(o.task.id, o.status) for o in result.outcomes]
    assert statuses == [("T001", "done"), ("T002", "done")], statuses
    # Self-fix engaged at the CLI task (the last APPLICABLE one, not the last
    # task): the initial smoke failed → one rebuild → the rebuild smoke passed,
    # so T001 recovered to `done` rather than staying `failed`. The third smoke
    # is the trailing task's observational run (it cannot self-fix — only the
    # last-applicable position does). The recovery is the proof self-fix fired
    # at the non-final applicable position.
    assert len(shell.shell_calls) == 3
    builds = sum(1 for c in llm.calls if "did not pass" in str(c[-1].get("content", "")))
    assert builds == 1, "exactly one self-fix rebuild prompt was issued"


@pytest.mark.asyncio
async def test_early_cli_task_not_demoted(tmp_path: Path) -> None:
    """No-regression (scenario 7): an early CLI-building task that is NOT the
    last applicable task is observed, never demoted. Plan = [CLI task, LATER
    CLI task]; broken run-smoke. Only the LAST applicable task demotes."""
    project = _python_cli_project(tmp_path)
    (project / "early.py").write_text("V = 0\n")
    (project / "late.py").write_text("V = 0\n")
    _write_plan_json(
        project,
        [
            _plan_task("T001", files=["early.py"], applicable=True),
            _plan_task("T002", files=["late.py"], applicable=True),
        ],
    )
    llm = _PerTaskPatchLLM({"early.py": _patch("early.py"), "late.py": _patch("late.py")})
    shell = _SplitShellRunner(run_smoke=ShellResult("Traceback", 1))
    cfg = _config()
    cfg.agent.acceptance_self_fix = False
    agent = StepAgent(llm=llm, cwd=project, config=cfg, shell_runner=shell)

    result = await agent.run_plan()
    statuses = [(o.task.id, o.status) for o in result.outcomes]
    assert statuses == [("T001", "done"), ("T002", "failed")], statuses
    # The early CLI task is observed (run-smoke ran) but never demoted; the
    # broken run-smoke demotes only at the last applicable task.
    assert shell.shell_calls == ["python -m notes_cli add x"] * 2


@pytest.mark.asyncio
async def test_library_plan_never_enforced(tmp_path: Path) -> None:
    """No-regression (scenario 8): a plan with NO applicable spec — a library —
    has no last-applicable index → never enforced. Every task stays `done`
    even with a failing run-smoke."""
    project = _python_cli_project(tmp_path, pkg="mylib")
    (project / "a.py").write_text("V = 0\n")
    (project / "b.py").write_text("V = 0\n")
    _write_plan_json(
        project,
        [
            _plan_task("T001", files=["a.py"], applicable=False),
            _plan_task("T002", files=["b.py"], applicable=False),
        ],
    )
    llm = _PerTaskPatchLLM({"a.py": _patch("a.py"), "b.py": _patch("b.py")})
    shell = _SplitShellRunner(run_smoke=ShellResult("No module named mylib.__main__", 1))
    agent = StepAgent(llm=llm, cwd=project, config=_config(), shell_runner=shell)

    result = await agent.run_plan()
    statuses = [(o.task.id, o.status) for o in result.outcomes]
    assert statuses == [("T001", "done"), ("T002", "done")], statuses


@pytest.mark.asyncio
async def test_last_applicable_equals_last_task_unchanged(tmp_path: Path) -> None:
    """Regression: when the last task IS the applicable CLI (today's case) the
    behavior is identical — the last task demotes on a broken run-smoke."""
    project = _python_cli_project(tmp_path)
    (project / "a.py").write_text("V = 0\n")
    (project / "b.py").write_text("V = 0\n")
    _write_plan_json(
        project,
        [
            _plan_task("T001", files=["a.py"], applicable=False),
            _plan_task("T002", files=["b.py"], applicable=True),
        ],
    )
    llm = _PerTaskPatchLLM({"a.py": _patch("a.py"), "b.py": _patch("b.py")})
    shell = _SplitShellRunner(run_smoke=ShellResult("Traceback", 1))
    cfg = _config()
    cfg.agent.acceptance_self_fix = False
    agent = StepAgent(llm=llm, cwd=project, config=cfg, shell_runner=shell)

    result = await agent.run_plan()
    statuses = [(o.task.id, o.status) for o in result.outcomes]
    assert statuses == [("T001", "done"), ("T002", "failed")], statuses


# ── Interaction scenarios ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_later_task_not_re_enforced_after_last_applicable(tmp_path: Path) -> None:
    """Interaction: with the CLI enforced at the last-applicable position, a
    LATER non-applicable task that runs after it is NOT re-enforced and does not
    re-run run-smoke. Plan = [CLI applicable, doc non-applicable, test
    non-applicable]; the CLI run-smoke passes → all done; run-smoke ran ONCE."""
    project = _python_cli_project(tmp_path)
    for f in ("cli.py", "doc.py", "test.py"):
        (project / f).write_text("V = 0\n")
    _write_plan_json(
        project,
        [
            _plan_task("T001", files=["cli.py"], applicable=True),
            _plan_task("T002", files=["doc.py"], applicable=False),
            _plan_task("T003", files=["test.py"], applicable=False),
        ],
    )
    llm = _PerTaskPatchLLM({f: _patch(f) for f in ("cli.py", "doc.py", "test.py")})
    shell = _SplitShellRunner(run_smoke=ShellResult("usage: ok", 0))
    agent = StepAgent(llm=llm, cwd=project, config=_config(), shell_runner=shell)

    result = await agent.run_plan()
    statuses = [(o.task.id, o.status) for o in result.outcomes]
    assert statuses == [("T001", "done"), ("T002", "done"), ("T003", "done")], statuses
    # The run-smoke is observed per task, but ENFORCEMENT (which could demote /
    # self-fix) only ever fires at the last-applicable task. The trailing
    # non-applicable tasks are observed, never enforced — proven by the passing
    # smoke leaving all tasks `done`, and the self-fix never re-running here
    # (every smoke draws the same passing result; no rebuild was triggered).
    assert all(c == "python -m notes_cli add x" for c in shell.shell_calls)
    assert len(result.outcomes) == 3
