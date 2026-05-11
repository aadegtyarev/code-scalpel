"""Live probe of `code_with_retry` on a self-contained sandbox project.

Mirror of `scripts/probe.py` for the `code` mode. Spins up a tiny
calc-with-broken-tests project in a tempdir, then asks the agent to
fix it. Reports per-attempt verdict + final `git diff` -style
summary so the human can see what the model actually did to the
files without launching the TUI.

Run: `source .venv/bin/activate && python scripts/probe_code.py`
Requires LM Studio on http://localhost:1234.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from code_scalpel.agent import StepAgent
from code_scalpel.config import AgentConfig, AppConfig, ModelProfile
from code_scalpel.llm.adapter import OpenAICompatibleAdapter

_CONFIG = AppConfig(
    profiles={
        "local": ModelProfile(
            provider="lmstudio",
            model="qwen/qwen2.5-coder-14b",
            temperature=0.2,  # code mode default
            seed=42,
        )
    },
    agent=AgentConfig(
        max_files=20,
        max_file_lines=200,
        iterative_patch_loop=True,
        max_debug_attempts=2,
    ),
)


_BROKEN_CALC = """\
def add(a, b):
    # BUG: should be addition, not subtraction
    return a - b


def multiply(a, b):
    return a * b
"""

_PASSING_TEST = """\
from calc import add, multiply


def test_add():
    assert add(2, 3) == 5
    assert add(0, 0) == 0
    assert add(-1, 1) == 0


def test_multiply():
    assert multiply(2, 3) == 6
"""


def _seed_project(root: Path) -> None:
    (root / "calc.py").write_text(_BROKEN_CALC)
    (root / "test_calc.py").write_text(_PASSING_TEST)


async def main() -> None:
    print("=" * 72)
    print("LIVE CODE PROBE — code_with_retry on a sandbox project")
    print("target: qwen2.5-coder-14b @ http://localhost:1234")
    print("=" * 72)

    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp)
        _seed_project(project)
        print(f"\nSandbox: {project}")
        print("Initial calc.py:")
        print(_indent(_BROKEN_CALC))

        llm = OpenAICompatibleAdapter(
            base_url="http://localhost:1234/v1",
            api_key="lm-studio",
            model="qwen/qwen2.5-coder-14b",
        )
        agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

        task = "fix the bug in calc.add so all tests pass"
        print(f"\nTask: {task}\n")

        result = await agent.code_with_retry(task)

        print(f"\nAttempts: {len(result.attempts)}")
        for i, attempt in enumerate(result.attempts, start=1):
            verdict = (
                "✓ tests passed"
                if attempt.tests_passed
                else ("✗ apply failed" if not attempt.apply_ok else "✗ tests failed")
            )
            print(f"\n  Attempt {i}: {verdict}")
            if attempt.apply_error:
                print(f"    apply error: {attempt.apply_error[:120]}")
            if attempt.test_output:
                first_line = attempt.test_output.split("\n", 1)[0]
                print(f"    pytest: {first_line[:120]}")
            edits_summary = ", ".join(e.path for e in attempt.edits) or "(no edits)"
            print(f"    edits: {edits_summary}")

        print("\nFinal calc.py on disk:")
        print(_indent((project / "calc.py").read_text()))

        passed = bool(result.attempts) and result.attempts[-1].tests_passed
        print("\n" + "=" * 72)
        print(f"RESULT: {'✓ tests green' if passed else '✗ tests still red — rollback ran'}")
        print("=" * 72)


def _indent(text: str, prefix: str = "    ") -> str:
    return "\n".join(prefix + line for line in text.splitlines())


if __name__ == "__main__":
    asyncio.run(main())
