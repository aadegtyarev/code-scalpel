"""End-to-end probe: run /go with every v0.8 / v0.9 / v0.10 / v0.11
opt-in turned on, on a real (small) project, and print what happens.

Unit tests and the narrow-pass probes already validated each piece
in isolation. This script answers the question we haven't asked
yet: «do they cohere on a single /go run, or do they trip over
each other?»

Run: `source .venv/bin/activate && python scripts/probe_e2e_forks.py`
Requires LM Studio at http://localhost:1234 with qwen2.5-coder-14b.

The probe builds a throw-away project in `/tmp/probe_e2e_<pid>/`
with a TASKS.md that contains exactly one task — and one obvious
architectural fork (cache backend choice). Then it runs run_plan
with:

  • auto_annotate_plan      = True   (v0.7)
  • per_step_review         = True   (v0.8)
  • test_sanity_pass        = True   (v0.8)
  • empty_test_detect       = True   (v0.9)
  • import_graph_check      = True   (v0.9)
  • lint_pass               = True   (v0.9)
  • auto_detect_forks       = True   (v0.11)
  • fork_auto_reviewed      = True   (v0.11)
  • trust                   = optimist  (so a human-fork falls
                              through to LocalMeta on no UI)

…and a `fork_resolver=HumanForker(ui_hook=None)` so the fork
resolution path engages without a TUI.

Output is verbose by design — every tool card prints to stdout so
the operator can see the full sequence: annotate → detect_forks →
resolve → builder → review → sanity → empty-test → import-graph →
lint. If any pass crashes, the rest of the run still proceeds —
that's part of the design (graceful degradation), and the probe
exposes whether the degradation message is honest.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path

# Make sure the package import works when the script is run directly
# from the repo root without `pip install -e`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from code_scalpel.config import (  # noqa: E402
    AgentConfig,
    AppConfig,
    ModelProfile,
)
from code_scalpel.runtime import Runtime  # noqa: E402
from code_scalpel.tools.agent_tools import ToolCall, ToolResult  # noqa: E402

# A task with an EXPLICIT architectural choice. We want detect_forks
# to find this — it's exactly the «cross-task decision with ≥2
# reasonable options» the detector is built for. If it returns
# empty here, the prompt needs tightening (or the constraint isn't
# strong enough). Either outcome is useful.
TASKS_MD = """\
## T001: Add a job queue for background work

Goal: introduce a job queue the rest of the app can submit
background jobs to. The queue runs jobs in a worker; jobs survive
process restarts.

Files: queue.py

Acceptance:
- submit(job) enqueues, run_worker() picks up and executes
- jobs survive a process restart (the queue is persistent)
- queue API works from synchronous and asynchronous callers

Test command: pytest

Choose a persistence backend appropriate for a small CLI project
that will run on developer laptops. Realistic options include:
sqlite, redis, postgres, a flat-file JSON store. Each has
trade-offs. Pick one and justify the decision in the code.
"""

GREET_PY = """\
def greet(name: str) -> str:
    return f"hello, {name}"
"""


def _config() -> AppConfig:
    return AppConfig(
        profiles={
            "local": ModelProfile(
                provider="lmstudio",
                model="qwen/qwen2.5-coder-14b",
                seed=42,
            )
        },
        agent=AgentConfig(
            max_files=200,
            max_file_lines=400,
            iterative_patch_loop=True,
            max_debug_attempts=1,
            trust="optimist",
            sandbox="off",  # bwrap would block writes outside /tmp/probe_e2e
            # Every v0.8/v0.9/v0.10/v0.11 opt-in turned on.
            auto_annotate_plan=True,
            per_step_review=True,
            test_sanity_pass=True,
            empty_test_detect=True,
            import_graph_check=True,
            lint_pass=True,
            auto_detect_forks=True,
            fork_auto_reviewed=True,
            fork_human_fallback="local_meta",
        ),
    )


def _print_card(call: ToolCall, result: ToolResult) -> None:
    """Mirror the TUI's chat card to stdout. Truncates body to keep
    the probe transcript readable."""
    head = f"[{'✓' if result.ok else '✗'}] {call.name}"
    body = result.output
    if len(body) > 600:
        body = body[:600] + "\n  …(truncated)"
    print(head)
    for line in body.splitlines():
        print(f"  {line}")
    print()


async def run() -> int:
    workdir = Path(tempfile.mkdtemp(prefix="probe_e2e_"))
    print("=== Probe e2e ===")
    print(f"workdir: {workdir}\n")
    try:
        # Seed the project so the builder has something to extend.
        (workdir / "greet.py").write_text(GREET_PY)
        (workdir / "test_greet.py").write_text(
            "from greet import greet\n\ndef test_smoke():\n    assert greet('a') == 'hello, a'\n"
        )
        (workdir / ".code-scalpel").mkdir()
        (workdir / ".code-scalpel" / "TASKS.md").write_text(TASKS_MD)

        cfg = _config()
        runtime = Runtime(cwd=workdir, config=cfg, with_memory=False)

        def on_tool(call: ToolCall, result: ToolResult) -> None:
            _print_card(call, result)

        def on_start(task) -> None:  # type: ignore[no-untyped-def]
            print(f"▶ START {task.id}: {task.title}\n")

        def on_end(outcome) -> None:  # type: ignore[no-untyped-def]
            print(f"⏹ END   {outcome.task.id}: {outcome.status}\n")

        result = await runtime.agent.run_plan(
            on_task_start=on_start,
            on_task_end=on_end,
            on_tool_executed=on_tool,
            fork_resolver=runtime.fork_resolver,
            max_tasks=1,
        )

        print("=== FINAL TASKS.md ===")
        print((workdir / ".code-scalpel" / "TASKS.md").read_text())

        print("=== SESSION STATS ===")
        print(runtime.session.stats_report(model="qwen/qwen2.5-coder-14b", mode="code"))

        print(
            f"\n=== RESULT: {result.stopped_reason} (tasks_completed={result.tasks_completed}) ==="
        )
        return 0 if result.tasks_completed >= 1 else 1
    finally:
        keep = os.environ.get("PROBE_KEEP")
        if keep:
            print(f"\n(workdir kept at {workdir})")
        else:
            shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
