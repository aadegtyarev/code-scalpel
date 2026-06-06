"""Per-task plan-level verification — the machine checks behind Definition-of-Done.

Extracted from the run_plan body alongside the strangle so PlanRunner stays
within the AI-specific file-length minimum, and so the verification block has a
cohesive home. A task that `code_with_retry` reported as `done` is demoted to
`failed` unless the enforcing machine checks pass:

  1. `Files:` — every declared path exists on disk.            (demoting)
  2. `Test command:` — exits 0 (with the legacy exit-4/5 leniency).  (demoting)
  3. Git HEAD advanced — the model (or the auto-commit hook) committed. (demoting)
  4. Acceptance run-smoke — ENFORCING WHERE APPLICABLE. The adapter hands
     back an `AcceptanceSpec`; the run-loop runs `spec.command`, records the
     verdict + surfaces a card, and demotes `done → failed` ONLY when
     `spec.applicable` (a task-declared B or derived-and-applicable C spec).
     A not-applicable spec (the default-floor A, or a derivation that found no
     runnable CLI deliverable — a library) is observational: recorded +
     surfaced, never demoted (the feature-2 no-regression behavior).

Checks 1-3 guard against the model claiming `done` after only partly executing
a task; they demote done→failed (no new status). Check 4 gates demotion on
`spec.applicable` — the CLI-vs-library discriminator born in the derivation,
carried by the adapter, read once here (`feat/acceptance-spec-in-tasks`). The
default-floor NEVER sets `applicable`, so a python LIBRARY (which
`PythonCliAdapter.detect` over-fires on) stays observational. The path carries
ZERO language strings — every "how to run this" is assembled inside the
`detect()`-selected adapter (KD1 generality). The acceptance run-smoke
command/verdict/reason/source are persisted to AgentState for feature 3.
"""

from __future__ import annotations

import dataclasses
import json
import shlex
from contextlib import suppress
from typing import TYPE_CHECKING

from code_scalpel.skills import acceptance_adapter
from code_scalpel.tools.agent_tools import ToolCall, ToolResult, execute

if TYPE_CHECKING:
    from collections.abc import Callable

    from code_scalpel.agent import StepAgent, TaskOutcome
    from code_scalpel.plan import Task

    OnToolExecuted = Callable[[ToolCall, ToolResult], None] | None


def _demote(outcome: TaskOutcome) -> TaskOutcome:
    """Demote a `done` outcome to `failed`, preserving every other field.

    `dataclasses.replace` keeps task/step_result (and any field a future
    TaskOutcome gains) intact — the three enforcing checks share this so a
    new field can't be silently dropped on a demotion path.
    """
    return dataclasses.replace(outcome, status="failed")


async def verify_task(
    agent: StepAgent,
    task: Task,
    outcome: TaskOutcome,
    head_before: str | None,
    on_tool_executed: OnToolExecuted = None,
) -> TaskOutcome:
    """Run checks 1-4 on a `done` outcome.

    Checks 1-3 may demote done→failed; check 4 (acceptance) demotes too, but
    ONLY where an applicable spec exists — otherwise observational (see
    module docstring).
    """
    from code_scalpel.agent import _parse_task_test_command, _verify_task_files

    if outcome.status != "done":
        return outcome

    files_ok, _missing = _verify_task_files(task, agent._cwd)
    if not files_ok:
        return _demote(outcome)

    cmd = _parse_task_test_command(task)
    # Skip plain `pytest` invocations — `_run_tests` already covered that.
    if cmd and cmd.strip() != "pytest":
        verify_ok = await agent._verify_task_test_command(cmd)
        if not verify_ok:
            return _demote(outcome)

    outcome = await _verify_head_advanced(agent, task, outcome, head_before)
    return await _verify_acceptance(agent, task, outcome, on_tool_executed)


async def _verify_head_advanced(
    agent: StepAgent,
    task: Task,
    outcome: TaskOutcome,
    head_before: str | None,
) -> TaskOutcome:
    if not (outcome.status == "done" and agent._config.agent.auto_git):
        return outcome
    head_after = await agent._git_head_sha()
    # Model didn't commit. Try the auto-commit hook before failing — pulling
    # commit out of the model's responsibilities is the only path to L4 on
    # qwen-14b (see article ch. 36-37 / plan §31 v0.13). When the hook lands
    # a commit, the task stays "done".
    if (
        head_after is None or head_after == head_before
    ) and agent._config.agent.auto_commit_on_done:
        await agent._auto_commit_task(task)
        head_after = await agent._git_head_sha()
    # If HEAD did NOT advance, the task is a no-op: the model touched no new
    # files (or wrote identical content), `git add -A` had nothing to stage.
    # We keep status="done" because files + test-command already passed — the
    # task is functionally complete, just adds no new commit (e.g. T_N+1
    # "write tests for T_N" the model already wrote under T_N; marking failed
    # here broke L4→L5 on the 2026-05-14 N=3 main runs). When HEAD advanced,
    # attribute the commit to any pending upstream forks.
    if head_after is not None and head_after != head_before and agent._upstream_queue is not None:
        # Defensive suppress: queue bookkeeping must never break /go.
        with suppress(Exception):
            agent._upstream_queue.record_commit(head_after)  # type: ignore[attr-defined]
    return outcome


async def _verify_acceptance(
    agent: StepAgent,
    task: Task,
    outcome: TaskOutcome,
    on_tool_executed: OnToolExecuted = None,
) -> TaskOutcome:
    """Verification #4 — run-smoke of the deliverable, ENFORCING where applicable.

    When `acceptance_adapter(root)` resolves (a python-cli project today),
    ask it for an `AcceptanceSpec`, run `spec.command`, RECORD the verdict
    (passed/failed/noop) and SURFACE a card. No acceptance adapter → a logged
    no-op. Demotion is gated on `spec.applicable`: an applicable spec
    (task-declared B or derived-applicable C) that does not pass demotes
    `done → failed`; a not-applicable spec (the default-floor A or a library)
    is recorded + surfaced but the outcome is returned unchanged (the feature-2
    no-regression behavior). The path references NO language string — the
    `applicable` bool is the only thing the loop reads (KD1 generality).
    """
    adapter = acceptance_adapter(agent._cwd)
    if adapter is None:
        # No acceptance adapter for this project type — logged no-op.
        _record_acceptance(agent, command=None, verdict="noop", reason=None, source=None)
        _emit_acceptance_card(on_tool_executed, command=None, ok=True, reason="no adapter")
        return outcome

    verdict, command, reason, applicable, source = await _run_smoke(agent, adapter, task)
    ok = verdict == "passed"
    card_reason = None if ok else reason
    if verdict == "noop":
        # An adapter that flags provides_acceptance but yields no runnable
        # spec — a visible no-op, not an unqualified pass (finding 6).
        card_reason = reason
        # Load-bearing invariant: a noop NEVER demotes. The demotion gate below
        # is `applicable and not ok`, so every noop return site MUST yield
        # applicable=False (review finding 8). Asserted here so a future
        # noop-with-applicable=True can't silently start false-demoting.
        assert not applicable, "a noop verdict must never be applicable (would false-demote)"
    _record_acceptance(agent, command=command, verdict=verdict, reason=reason, source=source)
    _emit_acceptance_card(on_tool_executed, command=command, ok=ok, reason=card_reason)
    # Enforce iff applicable: an applicable spec that did not pass demotes.
    # A not-applicable spec (floor / library) is observational — the outcome
    # from checks 1-3 stands (the load-bearing no-regression invariant).
    if applicable and not ok:
        return _demote(outcome)
    return outcome


def _emit_acceptance_card(
    on_tool_executed: OnToolExecuted,
    *,
    command: str | None,
    ok: bool,
    reason: str | None,
) -> None:
    """Surface the acceptance step via the existing on_tool_executed card seam.

    Rides the same synthetic-card pattern the per-step-review / annotation
    passes use, so the user sees the run-smoke command + ✓/✗ (and the no-op
    for unsupported types) without any structural TUI change.
    """
    if on_tool_executed is None:
        return
    if command is None:
        output = f"Acceptance run-smoke skipped ({reason})."
    elif ok:
        output = f"Acceptance run-smoke passed: {command}"
    else:
        output = f"Acceptance run-smoke failed ({reason}): {command}"
    call = ToolCall(name="acceptance", body=command or "")
    with suppress(Exception):
        on_tool_executed(call, ToolResult(call, output=output, ok=ok))


async def _run_smoke(
    agent: StepAgent,
    adapter: object,
    task: Task,
) -> tuple[str, str | None, str | None, bool, str | None]:
    """Execute the adapter's acceptance run-smoke.

    Returns `(verdict, command, reason, applicable, source)`. `verdict` is
    one of `passed` / `failed` / `noop`; `applicable` is the enforcement gate
    the caller demotes on. Runs the code-owned acceptance command at
    trust="yolo" through the same `execute()` boundary (so it inherits trust /
    policy / bwrap gating; timeout + sandbox from config — no magic number).
    Exit-0-or-fail: no exit-4/5 leniency. When `spec.expected` is non-empty, a
    `passed` verdict additionally requires it to appear in the output (the
    floor's `expected == ""` ⇒ exit-0-only). A malformed-args spec
    (`AcceptanceArgError`) → a `noop` fallback (the package is healthy; the
    SPEC is broken — never demote it as `pkg-unresolvable`, review finding 5).
    `resolve_pkg` raising (`ValueError`) → `failed`/`pkg-unresolvable`, with
    `source` recovered from the task and applicability from the adapter's
    `acceptance_applicable` (the single precedence source, review findings 3+6)
    so an applicable spec still demotes and a library still observes
    (failure-path 12); `spec is None` → a visible `noop` (finding 6).
    """
    from code_scalpel.skills.base import AcceptanceArgError

    try:
        spec = adapter.acceptance_spec(task)  # type: ignore[attr-defined]
    except AcceptanceArgError:
        # The args string could not be tokenized — a broken SPEC, not a broken
        # package. Recording a visible noop (no demotion) keeps a healthy
        # project from being false-failed; the malformed marker self-heals on
        # the next derivation run. Recover source from the task for feature 3.
        return "noop", None, "malformed-args", False, _task_acceptance_source(task)
    except ValueError:
        # `resolve_pkg` could not resolve a runnable package. Applicability and
        # source are properties of the TASK's acceptance representation, not of
        # pkg resolution — recover both so an applicable spec still demotes
        # (pkg-unresolvable) while a library observes (failure-path 12), and the
        # recorded verdict carries the real provenance feature 3 needs.
        return (
            "failed",
            None,
            "pkg-unresolvable",
            _adapter_applicable(adapter, task),
            _task_acceptance_source(task),
        )
    if spec is None:
        # An adapter that flags provides_acceptance but returns no spec — a
        # self-contradictory state. Record a visible no-op rather than passing
        # silently; nothing runnable to verify.
        return "noop", None, "no acceptance spec", False, None

    # `spec.command` is the adapter's code-owned argv-string (the verb is the
    # adapter's; only the args are model/human-influenced — KD3). Re-derive the
    # argv to prove no shell metacharacters/free-form text reach the shell,
    # then rebuild the string from that argv. asyncio-subprocess security
    # considerations: never pass untrusted input to a shell.
    # https://docs.python.org/3/library/asyncio-subprocess.html#security-considerations
    command = shlex.join(shlex.split(spec.command))
    call = ToolCall(name="shell_exec", body=json.dumps({"command": command}))
    result = await execute(
        call,
        agent._cwd,
        max_lines=agent._config.agent.max_file_lines,
        runner=agent._shell_runner,
        trust="yolo",
        shell_exec_timeout=agent._config.agent.shell_exec_timeout,
        sandbox=agent._config.agent.sandbox,
    )
    if not result.ok:
        return "failed", command, _failure_reason(result), spec.applicable, spec.source
    # Exit 0. With a non-empty `expected` observable the deliverable must also
    # actually print it — guards the false-green where a CLI exits 0 while
    # producing nothing. The floor (`expected == ""`) stays exit-0-only.
    if spec.expected and spec.expected not in result.output:
        return "failed", command, "expected-missing", spec.applicable, spec.source
    return "passed", command, None, spec.applicable, spec.source


def _adapter_applicable(adapter: object, task: Task) -> bool:
    """Enforcement-applicability via the adapter's single source.

    Used only on the `pkg-unresolvable` path where argv assembly raised before
    a spec could be built. Delegates to `adapter.acceptance_applicable(task)`
    — the SAME C→A precedence the adapter's `acceptance_spec` encodes — so the
    two never silently diverge (review finding 6). An adapter without the
    method (a future / minimal adapter) is treated as not-applicable (observe).
    No language string here.
    """
    fn = getattr(adapter, "acceptance_applicable", None)
    if fn is None:
        return False
    try:
        return bool(fn(task))
    except Exception:
        return False


def _task_acceptance_source(task: Task) -> str | None:
    """Recover the spec `source` from the task when argv assembly raised.

    A decodable derived marker → "derived"; otherwise None (the floor / no
    enforceable spec). Lets the recorded verdict carry the real provenance
    feature 3's self-fix keys off, even on the failure path (review finding 3).
    """
    from code_scalpel.skills.base import decode_derived_acceptance

    for line in tuple(getattr(task, "acceptance", ())):
        if decode_derived_acceptance(line) is not None:
            return "derived"
    return None


def _failure_reason(result: ToolResult) -> str:
    """Map a failed run-smoke ToolResult to a compact reason string.

    `ToolResult` carries no structured returncode (only `ok` + `output`), so
    the reason is parsed from the execute()-formatted output, whose shapes are
    code-owned in `agent_tools._tool_shell_exec`: a timeout is `timeout after
    <n>s`; a non-zero exit leads with `exit code: <n>`; a policy/sandbox
    refusal leads with `refused:`; an internal error with `error:`. The
    pass/fail decision is `result.ok` upstream — only the reason is parsed here.
    """
    out = result.output
    # Anchor the timeout match to the code-owned prefix — the bare substring
    # "timeout" can appear anywhere in a deliverable's own stdout.
    if out.startswith("timeout after "):
        return "timeout"
    stripped = out.lstrip()
    if stripped.startswith("refused:") or stripped.startswith("error:"):
        # Policy block / sandbox-unavailable / internal error — a distinct
        # reason so feature 3's self-fix can tell it apart from a real
        # non-zero exit (e.g. a missing-bwrap config, not broken code).
        return "refused"
    for line in out.splitlines():
        low = line.strip().lower()
        if low.startswith("exit code:"):
            return f"exit {low.removeprefix('exit code:').strip().split()[0]}"
    return "run-smoke failed"


def _record_acceptance(
    agent: StepAgent,
    *,
    command: str | None,
    verdict: str,
    reason: str | None,
    source: str | None,
) -> None:
    """Persist the last run-smoke command + verdict + reason + source to AgentState.

    Defensive suppress + the existing atomic save — acceptance bookkeeping
    must never break /go. No-op when no state is wired.

    A `noop` (the common non-python / no-adapter case) must NOT overwrite an
    earlier meaningful `passed`/`failed` verdict, and must NOT trigger a
    redundant atomic STATE.json write per task. We persist only when a real
    run-smoke verdict was produced, or when the value actually changes
    (finding 3). `source` (declared/derived/floor) rides alongside so
    feature 3's self-fix and metrics can tell where the spec came from.
    """
    if agent._state is None:
        return
    prior = getattr(agent._state, "last_acceptance_verdict", "unknown")
    # A noop never clobbers an earlier meaningful verdict.
    if verdict == "noop" and prior in ("passed", "failed"):
        return
    # Skip the redundant write when nothing changes (e.g. repeated noop).
    if (
        verdict == prior
        and getattr(agent._state, "last_acceptance_command", None) == command
        and getattr(agent._state, "last_acceptance_reason", None) == reason
        and getattr(agent._state, "last_acceptance_source", None) == source
    ):
        return
    with suppress(Exception):
        agent._state.last_acceptance_command = command  # type: ignore[attr-defined]
        agent._state.last_acceptance_verdict = verdict  # type: ignore[attr-defined]
        agent._state.last_acceptance_reason = reason  # type: ignore[attr-defined]
        agent._state.last_acceptance_source = source  # type: ignore[attr-defined]
    agent._persist_state()
