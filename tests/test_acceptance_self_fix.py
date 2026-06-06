"""Tests for the acceptance self-fix loop (feature 3).

`feat/acceptance-self-fix-loop` turns the acceptance gate's terminal
`done → failed` demotion into a bounded, trust-gated self-fix cycle: on a
failing FINAL-task run-smoke (intent × position × state) at `optimist`/`yolo`,
the run loop re-feeds the failing run-smoke output to `code_with_retry`,
rebuilds, and re-runs the smoke — up to `acceptance_self_fix_max_attempts`
times — before finally `failed`. At `skeptic`: `failed` immediately (unchanged).

The loop lives in `PlanRunner._run_task` / `_self_fix_acceptance` (KD1);
`verify_task` stays a pure reporter. These tests mirror the `_agent` / `_config`
/ `MockLLMAdapter` / `MockShellRunner` fixtures of `test_acceptance_enforcement.py`
and prove: recovery, budget exhaustion, the trust gate (machine check), the
off-switch, the identical-output break (KD5), the no-regression position/intent
gates, the inline signal wiring (KD2), the two failure paths, the HEAD
re-snapshot + commit interactions, and language-agnosticism (KD9). At least one
test drives the production `run_plan` loop (test-wiring-parity).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from code_scalpel.agent import StepAgent, StepResult, TaskOutcome
from code_scalpel.config import AgentConfig, AppConfig, ModelProfile
from code_scalpel.plan import Task
from code_scalpel.plan_runner import PlanRunner
from code_scalpel.skills.base import AcceptanceSpec, encode_derived_acceptance
from code_scalpel.state import AgentState
from code_scalpel.tools.shell import ShellResult
from tests.mocks import MockLLMAdapter, MockShellRunner

_SHELL_TIMEOUT = 17


def _config(trust: str = "yolo", *, self_fix: bool = True, max_attempts: int = 3) -> AppConfig:
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
            acceptance_self_fix=self_fix,
            acceptance_self_fix_max_attempts=max_attempts,
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
    # An anchor file the no-op build patch can always re-apply against.
    (tmp_path / "f.py").write_text("ANCHOR = 1\n")
    return tmp_path


# A SEARCH/REPLACE patch whose SEARCH == REPLACE: it applies as a no-op against
# the anchor file on EVERY build pass (including each self-fix rebuild), so the
# build always reaches `done` and the acceptance run-smoke is the only thing
# that can demote — exactly the condition the self-fix loop exists for.
_NOOP_PATCH = (
    "f.py\n```python\n<<<<<<< SEARCH\nANCHOR = 1\n=======\nANCHOR = 1\n>>>>>>> REPLACE\n```\n"
)


class _SmokeSeqRunner(MockShellRunner):
    """Tests (`run`, argv) always pass; the acceptance run-smoke (`run_shell`)
    draws from a caller-fixed sequence so each build → re-verify pass can see a
    different run-smoke verdict. The last item repeats once the sequence is
    exhausted (mirrors MockShellRunner's clamp)."""

    def __init__(self, *, smoke: list[ShellResult]) -> None:
        super().__init__()
        self._smoke = smoke
        self._i = 0

    async def run(self, cmd: list[str], cwd: str | None = None, timeout: int = 30) -> ShellResult:
        self.calls.append(cmd)
        return ShellResult("1 passed", 0)

    async def run_shell(
        self, command: str, cwd: str | None = None, timeout: int = 30
    ) -> ShellResult:
        self.shell_calls.append(command)
        res = self._smoke[min(self._i, len(self._smoke) - 1)]
        self._i += 1
        return res


def _agent(
    project: Path,
    shell: MockShellRunner,
    *,
    trust: str = "yolo",
    state: AgentState | None = None,
    llm: MockLLMAdapter | None = None,
    self_fix: bool = True,
    max_attempts: int = 3,
) -> StepAgent:
    return StepAgent(
        llm=llm or MockLLMAdapter([_NOOP_PATCH]),
        cwd=project,
        config=_config(trust, self_fix=self_fix, max_attempts=max_attempts),
        shell_runner=shell,
        state=state,
    )


def _derived_task(*, applicable: bool = True, args: str = "add x", expected: str = "") -> Task:
    marker = encode_derived_acceptance(applicable=applicable, args=args, expected=expected)
    return Task(
        id="T001", title="ship cli", body="", done=False, files=("f.py",), acceptance=(marker,)
    )


def _count_builds(agent: StepAgent) -> dict[str, int]:
    """Wrap `code_with_retry` to count invocations (one per build/rebuild pass);
    a single build is several LLM calls, so the pass count — not `llm._index` —
    is the right measure of how many times the builder ran."""
    counter = {"n": 0}
    real = agent.code_with_retry

    async def _counted(prompt: str, **kw: object) -> StepResult:
        counter["n"] += 1
        return await real(prompt, **kw)  # type: ignore[arg-type]

    agent.code_with_retry = _counted  # type: ignore[method-assign]
    return counter


async def _run_one(
    agent: StepAgent, task: Task, *, should_run_now: bool
) -> tuple[TaskOutcome, dict[str, int]]:
    """Drive the production `_run_task` path for one task and return the
    outcome plus a build-pass counter (so callers can assert the exact number
    of `code_with_retry` invocations — initial build + self-fix rebuilds)."""
    builds = _count_builds(agent)
    runner = PlanRunner(agent)
    outcome = await runner._run_task(task, should_run_now, None)
    return outcome, builds


def _smoke_passes() -> ShellResult:
    return ShellResult("usage: ok\n", 0)


def _smoke_fails(text: str = "Traceback: boom") -> ShellResult:
    return ShellResult(text, 1)


# ── Recovery / budget / trust ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_self_fix_recovers_task(tmp_path: Path) -> None:
    """optimist; applicable last task; run-smoke fails then passes after one
    rebuild → final status `done` (it would have been `failed` before this
    feature). Drives the production `_run_task` / run-loop path."""
    project = _python_cli_project(tmp_path)
    task = _derived_task()
    shell = _SmokeSeqRunner(smoke=[_smoke_fails("first boom"), _smoke_passes()])
    outcome, builds = await _run_one(_agent(project, shell), task, should_run_now=True)
    assert outcome.status == "done", "a recovered run-smoke must end done"
    assert builds["n"] == 2, "initial build + one self-fix rebuild"
    # First smoke failed (initial verify) → one rebuild → second smoke passed.
    assert len(shell.shell_calls) == 2
    assert shell.shell_calls == ["python -m notes_cli add x"] * 2


@pytest.mark.asyncio
async def test_self_fix_budget_exhausted_then_failed(tmp_path: Path) -> None:
    """optimist; run-smoke fails (with DISTINCT output each time so the
    identical-output break never fires) on every attempt → `failed` after
    exactly `max_attempts` self-fix rebuilds; `code_with_retry` is re-invoked
    the budgeted number of times (not more, not fewer)."""
    project = _python_cli_project(tmp_path)
    task = _derived_task()
    # 1 initial + 3 self-fix re-verifies, each a DISTINCT failure (no early break).
    shell = _SmokeSeqRunner(smoke=[_smoke_fails(f"boom {n}") for n in range(4)])
    outcome, builds = await _run_one(_agent(project, shell), task, should_run_now=True)
    assert outcome.status == "failed"
    # 1 initial build + 3 self-fix rebuilds = 4 code_with_retry passes.
    assert builds["n"] == 4
    # 1 initial smoke + 3 self-fix smokes = 4 run-smoke dispatches.
    assert len(shell.shell_calls) == 4


@pytest.mark.asyncio
async def test_skeptic_no_autofix(tmp_path: Path) -> None:
    """skeptic; applicable + last + failing run-smoke → `failed` and
    `code_with_retry` is invoked only for the INITIAL build, never re-invoked
    (the trust gate is a machine check via `policy.auto_confirm`)."""
    project = _python_cli_project(tmp_path)
    task = _derived_task()
    shell = _SmokeSeqRunner(smoke=[_smoke_fails()])
    outcome, builds = await _run_one(
        _agent(project, shell, trust="skeptic"), task, should_run_now=True
    )
    assert outcome.status == "failed", "skeptic fails immediately, no autofix"
    assert builds["n"] == 1, "only the initial build runs at skeptic"
    assert len(shell.shell_calls) == 1, "only the initial run-smoke at skeptic"


@pytest.mark.asyncio
async def test_self_fix_off_restores_immediate_failed(tmp_path: Path) -> None:
    """`acceptance_self_fix=False`; failing applicable final-task run-smoke →
    immediate `failed`, no rebuild (the feature-4 behavior, restorable by
    config)."""
    project = _python_cli_project(tmp_path)
    task = _derived_task()
    shell = _SmokeSeqRunner(smoke=[_smoke_fails()])
    outcome, builds = await _run_one(
        _agent(project, shell, self_fix=False), task, should_run_now=True
    )
    assert outcome.status == "failed"
    assert builds["n"] == 1, "self-fix off → no rebuild"
    assert len(shell.shell_calls) == 1


@pytest.mark.asyncio
async def test_identical_run_smoke_output_breaks_early(tmp_path: Path) -> None:
    """run-smoke output byte-identical across attempts → the loop stops before
    the full budget is spent (fewer rebuilds than `max_attempts`); task
    `failed` (the anti-loop guard, KD5)."""
    project = _python_cli_project(tmp_path)
    task = _derived_task()
    # Same failure text every time → identical-output break after the FIRST
    # self-fix rebuild (its smoke == the initial smoke).
    shell = _SmokeSeqRunner(smoke=[_smoke_fails("identical boom")])
    outcome, builds = await _run_one(
        _agent(project, shell, max_attempts=3), task, should_run_now=True
    )
    assert outcome.status == "failed"
    # 1 initial + 1 self-fix rebuild (then identical → stop) = 2, well under 4.
    assert builds["n"] == 2, "identical output must break before the budget is spent"
    assert len(shell.shell_calls) == 2


# ── No-regression: position / intent gates never self-fixed ──────────────────


@pytest.mark.asyncio
async def test_early_task_never_self_fixed(tmp_path: Path) -> None:
    """An applicable spec that is NOT `should_run_now` (an early task) is
    observed: failing run-smoke recorded, but the task stays `done`, no
    self-fix, no demotion (the no-regression invariant)."""
    project = _python_cli_project(tmp_path)
    task = _derived_task()
    shell = _SmokeSeqRunner(smoke=[_smoke_fails()])
    outcome, builds = await _run_one(_agent(project, shell), task, should_run_now=False)
    assert outcome.status == "done", "an early applicable task is observed, never self-fixed"
    assert builds["n"] == 1, "no rebuild for an early task"
    assert len(shell.shell_calls) == 1


@pytest.mark.asyncio
async def test_library_never_self_fixed(tmp_path: Path) -> None:
    """A not-applicable (library / floor) spec is observed even at the last
    task with a failing run-smoke: stays `done`, no self-fix, no demotion (the
    load-bearing no-regression invariant)."""
    project = _python_cli_project(tmp_path, pkg="mylib")
    task = _derived_task(applicable=False, args="")
    shell = _SmokeSeqRunner(smoke=[_smoke_fails("No module named mylib.__main__")])
    outcome, builds = await _run_one(_agent(project, shell), task, should_run_now=True)
    assert outcome.status == "done", "a library must never be self-fixed or demoted"
    assert builds["n"] == 1, "no rebuild for a not-applicable task"
    assert len(shell.shell_calls) == 1


# ── Inline signal wiring (KD2) ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_self_fix_signal_reaches_builder(tmp_path: Path) -> None:
    """The failing run-smoke output is what is handed to `code_with_retry` on
    the retry (the inline-signal of KD2 actually FLOWS; not just that a retry
    happened). The retry prompt contains the run-smoke output text and the
    adapter-built command."""
    project = _python_cli_project(tmp_path)
    task = _derived_task()
    shell = _SmokeSeqRunner(smoke=[_smoke_fails("UNIQUE-SMOKE-MARKER-9001"), _smoke_passes()])
    llm = MockLLMAdapter([_NOOP_PATCH])
    outcome, _llm = await _run_one(_agent(project, shell, llm=llm), task, should_run_now=True)
    assert outcome.status == "done"
    # The retry build's prompt (2nd chat call) carried the run-smoke output.
    retry_prompt = str(llm.calls[-1][-1].get("content", ""))
    assert "UNIQUE-SMOKE-MARKER-9001" in retry_prompt, "the run-smoke output must reach the builder"


# ── Failure paths 8 & 9 ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_self_fix_code_with_retry_raises(tmp_path: Path) -> None:
    """Failure path 8: `code_with_retry` raises during a self-fix attempt → the
    run loop does not crash, the task ends `failed`, partial progress preserved
    (the initial build's state stays on disk)."""
    project = _python_cli_project(tmp_path)
    task = _derived_task()
    shell = _SmokeSeqRunner(smoke=[_smoke_fails()])
    agent = _agent(project, shell)
    runner = PlanRunner(agent)

    calls = {"n": 0}
    real = agent.code_with_retry

    async def _flaky(prompt: str, **kw: object) -> StepResult:
        calls["n"] += 1
        if calls["n"] >= 2:  # raise on the first self-fix rebuild
            raise RuntimeError("rebuild engine blew up")
        return await real(prompt, **kw)  # type: ignore[arg-type]

    agent.code_with_retry = _flaky  # type: ignore[method-assign]
    outcome = await runner._run_task(task, True, None)
    assert outcome.status == "failed", "a builder raise must not crash the loop"


@pytest.mark.asyncio
async def test_self_fix_run_smoke_timeout_attempt(tmp_path: Path) -> None:
    """Failure path 9: a self-fix attempt's re-run-smoke times out (a distinct
    failure output) → it counts as a failed attempt and its output feeds the
    next attempt; a subsequent pass still recovers the task."""
    project = _python_cli_project(tmp_path)
    task = _derived_task()
    # initial exit-1 → rebuild → timeout → rebuild → pass.
    shell = _SmokeSeqRunner(
        smoke=[
            _smoke_fails("exit boom"),
            ShellResult(f"timeout after {_SHELL_TIMEOUT}s", 1),
            _smoke_passes(),
        ]
    )
    llm = MockLLMAdapter([_NOOP_PATCH])
    outcome, _llm = await _run_one(_agent(project, shell, llm=llm), task, should_run_now=True)
    assert outcome.status == "done"
    assert len(shell.shell_calls) == 3, "the timeout attempt counts and feeds the next"


# ── Interaction scenarios ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_head_resnapshotted_each_self_fix_attempt(tmp_path: Path) -> None:
    """A self-fix rebuild re-snapshots `head_before` so the HEAD-advance check
    is evaluated against THAT attempt's commit, never a stale prior sha. With
    `auto_git` on, the per-attempt build calls `_git_head_sha` fresh each time;
    a passing run-smoke after a rebuild lands `done`."""
    project = _python_cli_project(tmp_path)
    task = _derived_task()
    shell = _SmokeSeqRunner(smoke=[_smoke_fails(), _smoke_passes()])
    agent = _agent(project, shell)
    agent._config.agent.auto_git = True  # type: ignore[attr-defined]

    heads: list[str] = []

    async def _head() -> str:
        sha = f"sha{len(heads)}"
        heads.append(sha)
        return sha

    agent._git_head_sha = _head  # type: ignore[method-assign]
    # auto_commit_on_done off so the HEAD-advance check uses the snapshots only.
    agent._config.agent.auto_commit_on_done = False  # type: ignore[attr-defined]
    runner = PlanRunner(agent)
    outcome = await runner._run_task(task, True, None)
    assert outcome.status == "done"
    # _git_head_sha was queried fresh on the initial build AND the self-fix
    # rebuild — a re-snapshot per attempt, not one carried sha.
    assert len(heads) >= 2, "HEAD must be re-snapshotted per self-fix attempt"


@pytest.mark.asyncio
async def test_recovered_task_is_committed(tmp_path: Path) -> None:
    """A task recovered by self-fix is committed via the auto-commit-on-done
    hook like any `done` task — and the recovery produces exactly ONE net new
    commit (HEAD advances once), no double-commit. The hook is idempotent: it
    stages + commits pending work, and is a no-op when nothing is pending
    (mirroring the real `git add -A && git commit` which fails cleanly on an
    empty index), so a no-op rebuild does not pile on a second commit."""
    project = _python_cli_project(tmp_path)
    task = _derived_task()
    shell = _SmokeSeqRunner(smoke=[_smoke_fails(), _smoke_passes()])
    agent = _agent(project, shell)
    agent._config.agent.auto_git = True  # type: ignore[attr-defined]
    agent._config.agent.auto_commit_on_done = True  # type: ignore[attr-defined]

    # The model's first build produced pending changes; commits land them and
    # leave the index clean, so any later hook invocation is a no-op (the real
    # hook fails cleanly with nothing staged).
    state = {"head": 0, "pending": True}

    async def _head() -> str:
        return f"sha{state['head']}"

    commits = {"n": 0}

    async def _commit(_task: Task) -> bool:
        if state["pending"]:
            commits["n"] += 1
            state["head"] = int(state["head"]) + 1  # the commit advances HEAD
            state["pending"] = False
        return not state["pending"]

    agent._git_head_sha = _head  # type: ignore[method-assign]
    agent._auto_commit_task = _commit  # type: ignore[method-assign]
    runner = PlanRunner(agent)
    outcome = await runner._run_task(task, True, None)
    assert outcome.status == "done"
    # Exactly one net commit landed across the whole recovery — no double-commit.
    assert commits["n"] == 1, "a recovered task lands exactly one commit"
    assert state["head"] == 1, "HEAD advanced exactly once"


# ── Stack-spec tests ─────────────────────────────────────────────────────────


def test_self_fix_config_defaults() -> None:
    """`AgentConfig().acceptance_self_fix is True` and
    `acceptance_self_fix_max_attempts == 3` — defaults live in `config.py`
    (pydantic field defaults; no magic numbers in the loop).
    Ref: https://docs.pydantic.dev/latest/concepts/models/"""
    cfg = AgentConfig()
    assert cfg.acceptance_self_fix is True
    assert cfg.acceptance_self_fix_max_attempts == 3


@pytest.mark.asyncio
async def test_self_fix_language_agnostic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """With a NON-python mock adapter, the self-fix path runs using the
    adapter-provided command and contains NO python/`-m`/`notes_cli` literal in
    the run loop or the retry-prompt assembly — the loop is adapter-driven, not
    python-shaped (KD9). Ref: docs/architecture.md §"ProjectAdapter"."""

    class _FakeNodeAdapter:
        provides_acceptance = True

        def acceptance_spec(self, task: object) -> AcceptanceSpec:
            return AcceptanceSpec(
                command="node cli.js run", expected="", applicable=True, source="declared"
            )

    import code_scalpel.plan_verify as pv

    monkeypatch.setattr(pv, "acceptance_adapter", lambda root: _FakeNodeAdapter())
    # No python package layout — only the anchor file for the no-op build patch.
    (tmp_path / "f.py").write_text("ANCHOR = 1\n")
    task = Task(id="T001", title="t", body="", done=False, files=("f.py",))
    shell = _SmokeSeqRunner(smoke=[_smoke_fails("node error"), _smoke_passes()])
    llm = MockLLMAdapter([_NOOP_PATCH])
    outcome, _llm = await _run_one(_agent(tmp_path, shell, llm=llm), task, should_run_now=True)
    assert outcome.status == "done"
    # The run-smoke command came from the adapter — no python literal anywhere.
    assert shell.shell_calls == ["node cli.js run", "node cli.js run"]
    retry_prompt = str(llm.calls[-1][-1].get("content", ""))
    for forbidden in ("python", "-m", "notes_cli"):
        assert forbidden not in retry_prompt, f"language literal leaked into self-fix: {forbidden}"


# ── Production run_plan path (test-wiring-parity) ────────────────────────────


def _write_plan_json(project: Path, tasks: list[dict[str, object]]) -> None:
    cs = project / ".code-scalpel"
    cs.mkdir(parents=True, exist_ok=True)
    (cs / "TASKS.json").write_text(json.dumps({"tasks": tasks, "completed": []}) + "\n")


@pytest.mark.asyncio
async def test_self_fix_recovers_through_run_plan(tmp_path: Path) -> None:
    """test-wiring-parity: the WHOLE `run_plan` loop recovers the final task.

    A single-task CLI plan whose run-smoke fails then passes after one self-fix
    rebuild → the run ends with the task `done` (it would have been `failed`
    before this feature). Drives `StepAgent.run_plan` end-to-end."""
    project = _python_cli_project(tmp_path)
    marker = encode_derived_acceptance(applicable=True, args="add x", expected="")
    _write_plan_json(
        project,
        [
            {
                "id": "T001",
                "title": "ship cli",
                "goal": "ship the cli",
                "files": ["f.py"],
                "acceptance": [marker],
                "skills": [],
                "test_command": None,
            }
        ],
    )
    shell = _SmokeSeqRunner(smoke=[_smoke_fails("first boom"), _smoke_passes()])
    agent = _agent(project, shell, llm=MockLLMAdapter([_NOOP_PATCH]))
    result = await agent.run_plan()
    statuses = [(o.task.id, o.status) for o in result.outcomes]
    assert statuses == [("T001", "done")], statuses
    assert len(shell.shell_calls) == 2, "initial smoke + one recovering smoke"
