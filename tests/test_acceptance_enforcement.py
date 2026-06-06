"""Tests for verification #4 ENFORCEMENT + the args-only acceptance derivation.

`feat/acceptance-spec-in-tasks` gives the observational acceptance gate its
teeth: verification #4 demotes `done → failed` ONLY where an *applicable* spec
exists (task-declared B or narrow-pass-derived-applicable C); the default-floor
and a not-applicable derived result (a library) stay observational. These tests
drive the production `plan_verify.verify_task` / `PlanRunner` / registry /
`acceptance_adapter` path (test-wiring-parity), and prove the run-loop carries
ZERO language strings (the generality guard) and the model-derived check is
args-only (no shell injection — KD3).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from code_scalpel.agent import StepAgent, TaskOutcome
from code_scalpel.config import AgentConfig, AppConfig, ModelProfile
from code_scalpel.plan import Task
from code_scalpel.plan_verify import verify_task
from code_scalpel.skills.base import (
    AcceptanceSpec,
    Skill,
    decode_derived_acceptance,
    encode_derived_acceptance,
)
from code_scalpel.state import AgentState
from code_scalpel.tools.shell import ShellResult
from tests.mocks import MockLLMAdapter, MockShellRunner

_SHELL_TIMEOUT = 17


def _config(trust: str = "yolo", *, derive: bool = False) -> AppConfig:
    return AppConfig(
        profiles={"local": ModelProfile(provider="lmstudio", model="m", temperature=0.1)},
        agent=AgentConfig(
            max_files=2,
            max_file_lines=50,
            auto_git=False,
            sandbox="off",
            auto_annotate_plan=False,
            auto_derive_acceptance=derive,
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
    llm: MockLLMAdapter | None = None,
    derive: bool = False,
) -> StepAgent:
    return StepAgent(
        llm=llm or MockLLMAdapter(["x"]),
        cwd=project,
        config=_config(trust, derive=derive),
        shell_runner=shell,
        state=state,
    )


def _done(task: Task) -> TaskOutcome:
    from code_scalpel.agent import StepResult

    sr = StepResult(reply="ok", edits=[], response=None)  # type: ignore[arg-type]
    return TaskOutcome(task=task, step_result=sr, status="done")


# A task with a DERIVED-APPLICABLE marker written back into acceptance (the C
# path) — the adapter builds `python -m <pkg> add x` and the gate enforces it.
def _derived_task(*, applicable: bool, args: str = "add x", expected: str = "") -> Task:
    marker = encode_derived_acceptance(applicable=applicable, args=args, expected=expected)
    return Task(id="T001", title="ship cli", body="", done=False, acceptance=(marker,))


# A task with a human-DECLARED acceptance (the B path) — free PROSE bullets,
# never executed as argv (review finding 2). With no derived marker it falls
# through to the observational floor and is NEVER demoted.
_DECLARED_TASK = Task(
    id="T001",
    title="ship cli",
    body="",
    done=False,
    acceptance=("the note appears in the list",),
)


# ── AcceptanceSpec dataclass + encoding helpers ──────────────────────────────


def test_acceptance_spec_dataclass_shape() -> None:
    """`AcceptanceSpec` carries command/expected/applicable/source; `Skill`'s
    default `acceptance_spec` returns None; `PythonCliAdapter` returns a spec."""
    from code_scalpel.skills.python_cli_adapter import PythonCliAdapter

    spec = AcceptanceSpec(command="c", expected="e", applicable=True, source="declared")
    assert (spec.command, spec.expected, spec.applicable, spec.source) == (
        "c",
        "e",
        True,
        "declared",
    )

    class _Bare(Skill):
        def detect(self, root: Path) -> bool:
            return False

        def test_cmd(self, args: str = "") -> list[str]:
            return []

        def lint_cmd(self) -> list[str]:
            return []

    assert _Bare().acceptance_spec(task=None) is None
    # PythonCliAdapter returns an AcceptanceSpec (proved root-bound elsewhere).
    assert PythonCliAdapter.acceptance_spec.__doc__ is not None


def test_derived_marker_roundtrips() -> None:
    """The write-back marker encodes applicable+args+expected and round-trips;
    a non-marker line (human bullet) decodes to None so it never collides."""
    line = encode_derived_acceptance(applicable=True, args="add x", expected="x")
    data = decode_derived_acceptance(line)
    assert data == {"applicable": True, "args": "add x", "expected": "x"}
    # A human-declared prose bullet is not a marker.
    assert decode_derived_acceptance("the note appears in list output") is None
    # Distinguishes not-applicable (derived) from absent.
    na = decode_derived_acceptance(
        encode_derived_acceptance(applicable=False, args="", expected="")
    )
    assert na == {"applicable": False, "args": "", "expected": ""}


def test_acceptance_spec_precedence(tmp_path: Path) -> None:
    """Precedence is derived (C) → floor (A); human PROSE (B) is NOT a directly
    enforced spec — it falls through to the floor (review finding 2). A task
    carrying BOTH a derived marker and a prose bullet → derived; a task with
    ONLY prose → floor (observational, not applicable)."""
    from code_scalpel.skills.python_cli_adapter import PythonCliAdapter

    project = _python_cli_project(tmp_path)
    adapter = PythonCliAdapter(root=project)

    # A: no acceptance → floor, not applicable.
    floor = adapter.acceptance_spec(Task(id="T", title="t", body="", done=False))
    assert floor is not None and floor.source == "floor" and floor.applicable is False

    # B: human PROSE bullets are NOT a directly-enforced spec → fall to floor.
    declared = adapter.acceptance_spec(_DECLARED_TASK)
    assert declared is not None and declared.source == "floor" and declared.applicable is False
    # Crucially the floor runs `--help`, never the prose joined as argv.
    assert declared.command == "python -m notes_cli --help"

    # C: a derived marker present (even alongside a prose bullet) → derived.
    marker = encode_derived_acceptance(applicable=True, args="list", expected="x")
    mixed = Task(id="T", title="t", body="", done=False, acceptance=("a prose bullet", marker))
    derived = adapter.acceptance_spec(mixed)
    assert derived is not None and derived.source == "derived"
    assert derived.command == "python -m notes_cli list"


# ── Enforcement: demote where applicable ─────────────────────────────────────


@pytest.mark.asyncio
async def test_prose_declared_acceptance_is_never_false_demoted(tmp_path: Path) -> None:
    """Review finding 2 (binding invariant): a task with PROSE human acceptance
    and NO derived marker is NOT executed as argv — it falls through to the
    observational floor and STAYS `done` even when the floor run-smoke fails.
    Prose ("the note appears in the list") must never run as
    `python -m <pkg> the note appears in the list` and false-demote the task."""
    project = _python_cli_project(tmp_path)
    shell = MockShellRunner([ShellResult("Traceback", 1)])
    state = AgentState()
    out = await verify_task(
        _agent(project, shell, state=state), _DECLARED_TASK, _done(_DECLARED_TASK), None
    )
    assert out.status == "done", "prose acceptance must never false-demote"
    # The floor ran `--help`, NOT the prose joined as argv.
    assert shell.shell_calls == ["python -m notes_cli --help"]
    assert state.last_acceptance_source == "floor"


@pytest.mark.asyncio
async def test_prose_declared_acceptance_floor_passes_stays_done(tmp_path: Path) -> None:
    """The floor (`--help`) exits 0 for a prose-acceptance task → stays `done`,
    recorded as the floor (observational), never as a demoting declared spec."""
    project = _python_cli_project(tmp_path)
    shell = MockShellRunner([ShellResult("usage: notes_cli", 0)])
    state = AgentState()
    out = await verify_task(
        _agent(project, shell, state=state), _DECLARED_TASK, _done(_DECLARED_TASK), None
    )
    assert out.status == "done"
    assert state.last_acceptance_verdict == "passed"
    assert state.last_acceptance_source == "floor"


@pytest.mark.asyncio
async def test_enforce_on_derived_applicable_spec(tmp_path: Path) -> None:
    """A task with a written-back derived-applicable (C) spec is enforced —
    demoted on failure. Drives the production verify_task / registry path."""
    project = _python_cli_project(tmp_path)
    task = _derived_task(applicable=True, args="add x")
    shell = MockShellRunner([ShellResult("boom", 2)])
    state = AgentState()
    out = await verify_task(_agent(project, shell, state=state), task, _done(task), None)
    assert out.status == "failed"
    assert state.last_acceptance_source == "derived"
    # The executed command is the adapter's argv built from the derived args.
    assert shell.shell_calls == ["python -m notes_cli add x"]


@pytest.mark.asyncio
async def test_observational_when_derivation_not_applicable(tmp_path: Path) -> None:
    """No-regression, load-bearing: a derived NOT-applicable result (a library)
    is recorded but the task stays `done`, NOT demoted. Uses a real python-
    library shape (src-layout, package present, no CLI intent) to prove the
    feature-2 regression cannot return — even a non-zero run-smoke must not
    demote when applicable is False."""
    # A genuine library layout: a package with no CLI deliverable. The derived
    # marker says applicable=false; run-smoke even fails, but the task stays done.
    project = _python_cli_project(tmp_path, pkg="mylib")
    task = _derived_task(applicable=False, args="")
    shell = MockShellRunner([ShellResult("No module named mylib.__main__", 1)])
    state = AgentState()
    out = await verify_task(_agent(project, shell, state=state), task, _done(task), None)
    assert out.status == "done", "a not-applicable (library) task must NEVER be demoted"
    assert state.last_acceptance_verdict == "failed"
    assert state.last_acceptance_source == "derived"


@pytest.mark.asyncio
async def test_floor_only_is_observational(tmp_path: Path) -> None:
    """A project with an adapter but no declared/derived applicable spec →
    default-floor recorded `applicable:false`, not demoted, source=floor."""
    project = _python_cli_project(tmp_path)
    bare = Task(id="T001", title="t", body="", done=False)
    shell = MockShellRunner([ShellResult("Traceback", 1)])
    state = AgentState()
    out = await verify_task(_agent(project, shell, state=state), bare, _done(bare), None)
    assert out.status == "done"
    assert state.last_acceptance_source == "floor"


@pytest.mark.asyncio
async def test_expected_observable_enforced_on_applicable(tmp_path: Path) -> None:
    """A non-empty `expected` absent from output → demoted even on exit 0;
    present → stays done (the false-green guard, now with teeth)."""
    project = _python_cli_project(tmp_path)
    task = _derived_task(applicable=True, args="list", expected="buy milk")

    # Exit 0 but expected absent → demote.
    shell = MockShellRunner([ShellResult("nothing", 0)])
    state = AgentState()
    out = await verify_task(_agent(project, shell, state=state), task, _done(task), None)
    assert out.status == "failed"
    assert state.last_acceptance_reason == "expected-missing"

    # Expected present → stays done.
    shell2 = MockShellRunner([ShellResult("buy milk\n", 0)])
    out2 = await verify_task(_agent(project, shell2), task, _done(task), None)
    assert out2.status == "done"


# ── Generality: enforce through a non-python adapter ─────────────────────────


@pytest.mark.asyncio
async def test_run_loop_enforces_through_a_nonpython_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GENERALITY guard (PM constraint): a fake `provides_acceptance` adapter
    with NO python returning an applicable AcceptanceSpec → the run-loop demotes
    on failure through it. Proves the verify path holds zero language strings —
    it reads only `spec.applicable` and runs `spec.command`."""

    class _FakeNodeAdapter:
        provides_acceptance = True

        def acceptance_spec(self, task: object) -> AcceptanceSpec:
            # A non-python command the loop never special-cases.
            return AcceptanceSpec(
                command="node cli.js run", expected="", applicable=True, source="declared"
            )

    import code_scalpel.plan_verify as pv

    monkeypatch.setattr(pv, "acceptance_adapter", lambda root: _FakeNodeAdapter())
    task = Task(id="T001", title="t", body="", done=False)

    # Failure through the fake adapter → demote.
    shell = MockShellRunner([ShellResult("error", 1)])
    out = await verify_task(_agent(tmp_path, shell), task, _done(task), None)
    assert out.status == "failed"
    assert shell.shell_calls == ["node cli.js run"]

    # Success through the fake adapter → stays done. Same loop, no python.
    shell2 = MockShellRunner([ShellResult("ok", 0)])
    out2 = await verify_task(_agent(tmp_path, shell2), task, _done(task), None)
    assert out2.status == "done"


# ── Args-only: no shell injection ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_derived_command_is_args_only_adapter_built(tmp_path: Path) -> None:
    """A model `args` with shell metacharacters does NOT produce a shell
    injection: the adapter tokenizes them into literal argv (the verb is
    code-owned `python -m <pkg>`), so no `;`/`&&`/`$()` reaches a shell as a
    command. Cites asyncio-subprocess security considerations — never pass
    untrusted input to a shell:
    https://docs.python.org/3/library/asyncio-subprocess.html#security-considerations
    """
    import shlex

    project = _python_cli_project(tmp_path)
    # A malicious model arg trying to chain `rm -rf ~`.
    task = _derived_task(applicable=True, args="add 'x'; rm -rf ~")
    shell = MockShellRunner([ShellResult("ok", 0)])
    await verify_task(_agent(project, shell), task, _done(task), None)
    command = shell.shell_calls[0]
    argv = shlex.split(command)
    # The verb stays code-owned; the metacharacters are quoted argv tokens.
    assert argv[:3] == ["python", "-m", "notes_cli"]
    # `rm` is NOT a standalone command token — it is inside a single quoted arg.
    assert "rm" in command  # appears as data
    assert shlex.join(argv) == command  # the command IS the argv joined, no shell ops added


def test_acceptance_command_argv_no_shell(tmp_path: Path) -> None:
    """Stack-spec: the acceptance command is argv-built; model args with
    metacharacters are a single quoted token, not shell operators. Cites the
    asyncio-subprocess security URL:
    https://docs.python.org/3/library/asyncio-subprocess.html#security-considerations
    """
    import shlex

    from code_scalpel.skills.python_cli_adapter import PythonCliAdapter

    project = _python_cli_project(tmp_path)
    task = _derived_task(applicable=True, args="add '$(whoami)'")
    spec = PythonCliAdapter(root=project).acceptance_spec(task)
    assert spec is not None
    argv = shlex.split(spec.command)
    # `$(whoami)` survives as a literal argv token, never command-substituted.
    assert "$(whoami)" in argv
    assert argv[:3] == ["python", "-m", "notes_cli"]


# ── pkg-unresolvable: applicable demotes vs not-applicable observes ──────────


@pytest.mark.asyncio
async def test_applicable_pkg_unresolvable_demotes_vs_notapplicable_observes(
    tmp_path: Path,
) -> None:
    """Failure-path 12: `resolve_pkg` raises → an APPLICABLE spec demotes
    (`pkg-unresolvable`); a NOT-applicable task observes (no demote). The
    applicability flag, not the error, decides enforcement."""
    # A flat-layout python project (pyproject, no resolvable package).
    applicable_proj = tmp_path / "app"
    applicable_proj.mkdir()
    (applicable_proj / "pyproject.toml").write_text("[project]\nname='x'\n")
    task_app = _derived_task(applicable=True, args="run")
    shell = MockShellRunner([])
    state = AgentState()
    out = await verify_task(
        _agent(applicable_proj, shell, state=state), task_app, _done(task_app), None
    )
    assert out.status == "failed"
    assert state.last_acceptance_reason == "pkg-unresolvable"
    assert shell.shell_calls == []  # raised before any shell dispatch

    # Same unresolvable condition, but a NOT-applicable task → observe.
    na_proj = tmp_path / "lib"
    na_proj.mkdir()
    (na_proj / "pyproject.toml").write_text("[project]\nname='y'\n")
    task_na = _derived_task(applicable=False, args="")
    state2 = AgentState()
    out2 = await verify_task(
        _agent(na_proj, MockShellRunner([]), state=state2), task_na, _done(task_na), None
    )
    assert out2.status == "done"
    assert state2.last_acceptance_reason == "pkg-unresolvable"


# ── The derivation pre-pass (production load_plan) ───────────────────────────


def _write_plan_json(project: Path, tasks: list[dict[str, object]]) -> None:
    cs = project / ".code-scalpel"
    cs.mkdir(parents=True, exist_ok=True)
    (cs / "TASKS.json").write_text(json.dumps({"tasks": tasks, "completed": []}) + "\n")


def _plan_task(tid: str = "T001", **over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": tid,
        "title": "ship cli",
        "goal": "ship the cli",
        "files": [],
        "acceptance": [],
        "skills": [],
        "test_command": None,
    }
    base.update(over)
    return base


@pytest.mark.asyncio
async def test_derivation_uses_json_schema_structured_output(tmp_path: Path) -> None:
    """Stack-spec: the derivation pass is configured with `output_schema`
    (sampler-enforced JSON via response_format=json_schema), not prompt-parsed.
    Cites narrow_pass / LM Studio json_schema (narrow_pass.py docstring)."""
    project = _python_cli_project(tmp_path)
    llm = MockLLMAdapter([json.dumps({"applicable": True, "args": "add x", "expected": "x"})])
    agent = _agent(project, MockShellRunner([]), llm=llm)
    task = Task(id="T001", title="t", body="", done=False, goal="g")
    data = await agent.derive_acceptance_args(task)
    assert data == {"applicable": True, "args": "add x", "expected": "x"}
    # The chat call carried a json_schema response_format (sampler-enforced).
    rf = llm.kwargs_calls[-1].get("response_format")
    assert rf is not None and rf["type"] == "json_schema"
    assert rf["json_schema"]["name"] == "derive_acceptance"


@pytest.mark.asyncio
async def test_derived_spec_written_back_not_rederived(tmp_path: Path) -> None:
    """After the pre-loop derivation, the task's acceptance is persisted into
    TASKS.json; a second load uses it WITHOUT a second derivation LLM call."""
    from code_scalpel.plan import parse_tasks_json
    from code_scalpel.plan_loading import load_plan

    project = _python_cli_project(tmp_path)
    _write_plan_json(project, [_plan_task()])
    # One derivation reply; if the loop re-derived, the queue would be exhausted.
    llm = MockLLMAdapter([json.dumps({"applicable": True, "args": "add x", "expected": "x"})])
    agent = _agent(project, MockShellRunner([]), llm=llm, derive=True)

    loaded = await load_plan(agent, None, None)
    assert loaded is not None
    tasks, _path, _hash = loaded
    # The derived marker landed in the in-loop typed task (no markdown drop).
    assert any(decode_derived_acceptance(b) for b in tasks[0].acceptance)

    # Persisted to TASKS.json — round-trips via parse_tasks_json.
    on_disk = parse_tasks_json((project / ".code-scalpel" / "TASKS.json").read_text())
    assert any(decode_derived_acceptance(b) for b in on_disk[0].acceptance)
    derivation_calls = llm._index

    # A second load must NOT re-derive: the acceptance is already present.
    llm2 = MockLLMAdapter([])  # empty queue — any LLM call would error
    agent2 = _agent(project, MockShellRunner([]), llm=llm2, derive=True)
    loaded2 = await load_plan(agent2, None, None)
    assert loaded2 is not None
    assert llm2._index == 0, "a written-back spec must not be re-derived"
    assert derivation_calls == 1


@pytest.mark.asyncio
async def test_derivation_failure_falls_back_observational(tmp_path: Path) -> None:
    """Failure-path 9: the narrow pass returns non-conforming JSON → the task
    is left untouched (no marker), falls back to the observational floor, no
    crash, no fabricated enforcing spec."""
    from code_scalpel.plan_loading import load_plan

    project = _python_cli_project(tmp_path)
    _write_plan_json(project, [_plan_task()])
    llm = MockLLMAdapter(["not json at all"])
    agent = _agent(project, MockShellRunner([]), llm=llm, derive=True)
    loaded = await load_plan(agent, None, None)
    assert loaded is not None
    tasks, _path, _hash = loaded
    # No marker written → falls back to floor (not applicable, observational).
    assert not any(decode_derived_acceptance(b) for b in tasks[0].acceptance)


@pytest.mark.asyncio
async def test_writeback_failure_uses_inmemory_and_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Failure-path 10: a write-back disk error → the derived spec is used
    in-memory this run (the typed tasks carry it), no crash, and the sentinel
    is the OLD hash so the loop does not stop with plan_modified."""
    import code_scalpel.plan_loading as pl
    from code_scalpel.plan import render_tasks_markdown

    project = _python_cli_project(tmp_path)
    _write_plan_json(project, [_plan_task()])

    # Force the atomic write to raise inside the persist step.
    def _boom(path: Path, content: str) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(pl, "_atomic_write", _boom, raising=False)
    # _atomic_write is imported inside the function; patch agent's symbol too.
    import code_scalpel.agent as ag

    monkeypatch.setattr(ag, "_atomic_write", _boom)

    llm = MockLLMAdapter([json.dumps({"applicable": True, "args": "add x", "expected": "x"})])
    agent = _agent(project, MockShellRunner([]), llm=llm, derive=True)
    loaded = await load_plan_safe(agent)
    tasks, _path, sentinel = loaded
    # In-memory derived spec survived despite the disk failure.
    assert any(decode_derived_acceptance(b) for b in tasks[0].acceptance)
    # Sentinel matches the ON-DISK markdown (unchanged), not the in-memory text.
    from code_scalpel.agent import _hash_text

    on_disk_md = (project / ".code-scalpel" / "TASKS.md").read_text()
    assert sentinel == _hash_text(on_disk_md)
    assert sentinel != _hash_text(render_tasks_markdown(tasks))


async def load_plan_safe(agent: StepAgent):  # type: ignore[no-untyped-def]
    from code_scalpel.plan_loading import load_plan

    loaded = await load_plan(agent, None, None)
    assert loaded is not None
    return loaded


# ── Interaction scenarios ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_writeback_not_flagged_as_plan_modified(tmp_path: Path) -> None:
    """The derivation write-back is the loop's OWN edit: the returned sentinel
    hashes the freshly-written markdown, so the per-task plan-modification check
    (`_hash_text(disk) == initial_hash`) does NOT trip."""
    from code_scalpel.agent import _hash_text

    project = _python_cli_project(tmp_path)
    _write_plan_json(project, [_plan_task()])
    llm = MockLLMAdapter([json.dumps({"applicable": True, "args": "add x", "expected": "x"})])
    agent = _agent(project, MockShellRunner([]), llm=llm, derive=True)
    _tasks, tasks_path, sentinel = await load_plan_safe(agent)
    # The loop reads disk + hashes; it must equal the returned sentinel.
    assert _hash_text(tasks_path.read_text()) == sentinel


@pytest.mark.asyncio
async def test_annotation_and_derivation_compose(tmp_path: Path) -> None:
    """Both pre-passes run without clobbering each other's write-backs: skill
    annotation then acceptance derivation; the final task carries the derived
    acceptance and the on-disk JSON round-trips it."""
    from code_scalpel.plan import parse_tasks_json
    from code_scalpel.plan_loading import load_plan

    project = _python_cli_project(tmp_path)
    _write_plan_json(project, [_plan_task()])
    # Annotation reply (markdown plan w/ Skills) + derivation reply (JSON).
    annotated = "## T001: ship cli\n\nGoal: ship the cli\nSkills: python\n"
    llm = MockLLMAdapter(
        [annotated, json.dumps({"applicable": True, "args": "add x", "expected": "x"})]
    )
    cfg = _config(derive=True)
    cfg.agent.auto_annotate_plan = True
    agent = StepAgent(llm=llm, cwd=project, config=cfg, shell_runner=MockShellRunner([]))
    loaded = await load_plan(agent, None, None)
    assert loaded is not None
    tasks, _path, _hash = loaded
    assert any(decode_derived_acceptance(b) for b in tasks[0].acceptance)
    on_disk = parse_tasks_json((project / ".code-scalpel" / "TASKS.json").read_text())
    assert any(decode_derived_acceptance(b) for b in on_disk[0].acceptance)


@pytest.mark.asyncio
async def test_derived_spec_resumes_from_plan(tmp_path: Path) -> None:
    """A resumed run reads the written-back spec instead of re-deriving: a
    TASKS.json already carrying a derived marker triggers no derivation call."""
    from code_scalpel.plan_loading import load_plan

    project = _python_cli_project(tmp_path)
    marker = encode_derived_acceptance(applicable=True, args="add x", expected="x")
    _write_plan_json(project, [_plan_task(acceptance=[marker])])
    llm = MockLLMAdapter([])  # empty — any derivation call errors
    agent = _agent(project, MockShellRunner([]), llm=llm, derive=True)
    loaded = await load_plan(agent, None, None)
    assert loaded is not None
    assert llm._index == 0, "an existing derived spec must not be re-derived on resume"


@pytest.mark.asyncio
async def test_acceptance_runs_at_yolo_on_skeptic_project(tmp_path: Path) -> None:
    """Enforcement executes the adapter-built args-only command at trust=yolo on
    a skeptic-trust project (plan-owned check) — no confirmation handler, and
    the demotion still fires on failure."""
    project = _python_cli_project(tmp_path)
    task = _derived_task(applicable=True, args="add x")
    shell = MockShellRunner([ShellResult("error", 1)])
    out = await verify_task(_agent(project, shell, trust="skeptic"), task, _done(task), None)
    assert out.status == "failed"
    assert shell.shell_calls == ["python -m notes_cli add x"]


# ── State persists source ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_state_persists_source(tmp_path: Path) -> None:
    """The acceptance `source` round-trips through AgentState; an old STATE.json
    without it loads with the None default (forward-compatible)."""
    project = _python_cli_project(tmp_path)
    task = _derived_task(applicable=True, args="add x")
    shell = MockShellRunner([ShellResult("ok", 0)])
    state = AgentState()
    await verify_task(_agent(project, shell, state=state), task, _done(task), None)
    assert state.last_acceptance_source == "derived"
    state.save(project)
    assert AgentState.load(project).last_acceptance_source == "derived"

    legacy = '{"current_task": null, "completed_tasks": []}'
    (project / ".code-scalpel").mkdir(exist_ok=True)
    (project / ".code-scalpel" / "STATE.json").write_text(legacy)
    assert AgentState.load(project).last_acceptance_source is None


# ── Review-fix coverage: composition preserves typed fields, marker self-heal ─


@pytest.mark.asyncio
async def test_pre_passes_preserve_typed_fields(tmp_path: Path) -> None:
    """Review finding 1 (BLOCKING): a fresh JSON plan with goal+files+
    test_command but NO skills and NO acceptance must keep ALL typed fields
    intact after BOTH pre-passes run (skill annotation + acceptance derivation).
    The annotation change-path must merge skills into the TYPED tasks (not
    re-parse markdown, which strips typed fields), and derivation must run on
    the full typed task and never persist a field-stripped plan."""
    from code_scalpel.plan import parse_tasks_json
    from code_scalpel.plan_loading import load_plan

    project = _python_cli_project(tmp_path)
    _write_plan_json(
        project,
        [
            _plan_task(
                goal="ship the notes cli",
                files=["src/notes_cli/__main__.py"],
                test_command="pytest -q",
            )
        ],
    )
    # Annotation reply adds Skills; derivation reply adds the marker.
    annotated = "## T001: ship cli\n\nGoal: ship the notes cli\nSkills: python\n"
    llm = MockLLMAdapter(
        [annotated, json.dumps({"applicable": True, "args": "add x", "expected": "x"})]
    )
    cfg = _config(derive=True)
    cfg.agent.auto_annotate_plan = True
    agent = StepAgent(llm=llm, cwd=project, config=cfg, shell_runner=MockShellRunner([]))
    loaded = await load_plan(agent, None, None)
    assert loaded is not None
    tasks, _path, _hash = loaded

    # In-loop typed task keeps every typed field AND carries the derived marker.
    t = tasks[0]
    assert t.goal == "ship the notes cli"
    assert t.files == ("src/notes_cli/__main__.py",)
    assert t.test_command == "pytest -q"
    assert "python" in t.skills
    assert any(decode_derived_acceptance(b) for b in t.acceptance)

    # The on-disk TASKS.json was NOT field-stripped — goal/files/test_command
    # survive the write-back, and the derived marker is persisted.
    on_disk = parse_tasks_json((project / ".code-scalpel" / "TASKS.json").read_text())[0]
    assert on_disk.goal == "ship the notes cli"
    assert on_disk.files == ("src/notes_cli/__main__.py",)
    assert on_disk.test_command == "pytest -q"
    assert any(decode_derived_acceptance(b) for b in on_disk.acceptance)


@pytest.mark.asyncio
async def test_prose_acceptance_feeds_derivation_as_hint(tmp_path: Path) -> None:
    """Review finding 2: a task with PROSE human acceptance and an acceptance
    adapter gets DERIVED (the prose is passed to the model as a hint, not run
    as argv). The derived marker replaces the prose; the executed spec is the
    derived (C) one."""
    from code_scalpel.plan_loading import load_plan

    project = _python_cli_project(tmp_path)
    _write_plan_json(project, [_plan_task(acceptance=["the note appears in the list"])])
    llm = MockLLMAdapter([json.dumps({"applicable": True, "args": "list", "expected": "note"})])
    agent = _agent(project, MockShellRunner([]), llm=llm, derive=True)
    loaded = await load_plan(agent, None, None)
    assert loaded is not None
    tasks, _path, _hash = loaded
    # Prose triggered derivation (one LLM call) and was replaced by the marker.
    assert llm._index == 1
    data = next(decode_derived_acceptance(b) for b in tasks[0].acceptance)
    assert data == {"applicable": True, "args": "list", "expected": "note"}
    assert "the note appears in the list" not in tasks[0].acceptance


@pytest.mark.asyncio
async def test_undecodable_marker_is_rederived(tmp_path: Path) -> None:
    """Review finding 4: a `derived-acceptance:`-prefixed line with malformed
    JSON is treated as ABSENT — the derivation gate re-derives it (rather than
    skipping because acceptance is non-empty), so a corrupt write-back self-
    heals instead of wedging the task."""
    from code_scalpel.plan_loading import load_plan

    project = _python_cli_project(tmp_path)
    _write_plan_json(project, [_plan_task(acceptance=["derived-acceptance:{not json"])])
    llm = MockLLMAdapter([json.dumps({"applicable": True, "args": "add x", "expected": "x"})])
    agent = _agent(project, MockShellRunner([]), llm=llm, derive=True)
    loaded = await load_plan(agent, None, None)
    assert loaded is not None
    tasks, _path, _hash = loaded
    assert llm._index == 1, "an undecodable marker must be re-derived (treated as absent)"
    assert any(decode_derived_acceptance(b) for b in tasks[0].acceptance)


@pytest.mark.asyncio
async def test_undecodable_marker_not_fed_as_args(tmp_path: Path) -> None:
    """Review finding 4 (adapter side): an undecodable marker is NOT fed as a
    derived spec — `acceptance_spec` falls through to the observational floor
    (never enforces garbage), and the verify path does NOT demote."""
    from code_scalpel.skills.python_cli_adapter import PythonCliAdapter

    project = _python_cli_project(tmp_path)
    task = Task(
        id="T001",
        title="t",
        body="",
        done=False,
        acceptance=("derived-acceptance:{broken",),
    )
    spec = PythonCliAdapter(root=project).acceptance_spec(task)
    assert spec is not None and spec.source == "floor" and spec.applicable is False
    assert spec.command == "python -m notes_cli --help"

    # And through the verify path: a failing floor must not demote.
    shell = MockShellRunner([ShellResult("Traceback", 1)])
    out = await verify_task(_agent(project, shell), task, _done(task), None)
    assert out.status == "done"


@pytest.mark.asyncio
async def test_malformed_args_falls_back_not_pkg_unresolvable(tmp_path: Path) -> None:
    """Review finding 5: a derived spec whose `args` have unbalanced quotes
    raises AcceptanceArgError inside run_smoke — a SPEC error, NOT a package
    error. The verify path records a `noop`/`malformed-args` fallback and does
    NOT demote the (healthy) project as `pkg-unresolvable`."""
    project = _python_cli_project(tmp_path)
    # Unbalanced quote in the derived args → shlex.split raises.
    task = _derived_task(applicable=True, args="add 'unterminated")
    shell = MockShellRunner([])
    state = AgentState()
    out = await verify_task(_agent(project, shell, state=state), task, _done(task), None)
    assert out.status == "done", "a malformed-args spec must not demote a healthy package"
    assert state.last_acceptance_verdict == "noop"
    assert state.last_acceptance_reason == "malformed-args"
    assert state.last_acceptance_reason != "pkg-unresolvable"
    assert shell.shell_calls == []  # never dispatched


@pytest.mark.asyncio
async def test_pkg_unresolvable_recovers_source_for_derived(tmp_path: Path) -> None:
    """Review finding 3: when resolve_pkg raises for a DERIVED task, the recorded
    verdict carries the real `source` (derived) — not None — so feature 3's
    self-fix has the provenance it keys off, and the applicable spec still
    demotes (`pkg-unresolvable`)."""
    proj = tmp_path / "app"
    proj.mkdir()
    (proj / "pyproject.toml").write_text("[project]\nname='x'\n")  # no resolvable pkg
    task = _derived_task(applicable=True, args="run")
    state = AgentState()
    out = await verify_task(_agent(proj, MockShellRunner([]), state=state), task, _done(task), None)
    assert out.status == "failed"
    assert state.last_acceptance_reason == "pkg-unresolvable"
    assert state.last_acceptance_source == "derived"


@pytest.mark.asyncio
async def test_wholesale_derivation_outage_surfaces(tmp_path: Path) -> None:
    """Review finding 7: when EVERY derivation errors (LLM down), a distinct
    not-ok card is surfaced so the silent floor-everywhere is visible — it must
    NOT read as a quiet 'no enforceable specs' success."""
    from code_scalpel.plan_loading import load_plan
    from code_scalpel.tools.agent_tools import ToolCall, ToolResult

    project = _python_cli_project(tmp_path)
    _write_plan_json(project, [_plan_task()])
    llm = MockLLMAdapter(["not json at all"])  # derivation errors
    agent = _agent(project, MockShellRunner([]), llm=llm, derive=True)

    cards: list[tuple[str, bool]] = []

    def _on(call: ToolCall, res: ToolResult) -> None:
        cards.append((res.output, res.ok))

    loaded = await load_plan(agent, _on, None)
    assert loaded is not None
    outage = [c for c in cards if "FAILED for all" in c[0]]
    assert outage and outage[0][1] is False, "a wholesale outage must surface a not-ok card"
