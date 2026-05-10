"""Benchmark: can qwen2.5-coder-14b stably produce applicable patches?

Each parametrized case sets up a tiny git repo, asks the model to make a change,
applies the produced patch, then asserts the post-state. Skipped by default —
run with `pytest --run-llm -m llm` to validate the model end-to-end.

We assert the *outcome* (substring or AST check on the patched file), not the
exact diff text — qwen output is non-deterministic even with seed=42 at this
scale.
"""

from __future__ import annotations

import ast
import textwrap
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from code_scalpel.agent import StepAgent
from code_scalpel.config import AgentConfig, AppConfig, ModelProfile
from code_scalpel.llm.adapter import OpenAICompatibleAdapter
from code_scalpel.patch.edit_block import apply_edits
from code_scalpel.tools.shell import AsyncShellRunner

_PROFILE = ModelProfile(
    provider="lmstudio",
    model="qwen/qwen2.5-coder-14b",
    temperature=0.1,
    seed=42,
)
_CONFIG = AppConfig(
    profiles={"local": _PROFILE},
    agent=AgentConfig(max_files=3, max_file_lines=120),
)


@dataclass(frozen=True)
class BenchTask:
    name: str
    files: dict[str, str]
    prompt: str
    check: Callable[[Path], None]


# ── assertion helpers ─────────────────────────────────────────────────────────


def _file_contains(rel: str, *needles: str) -> Callable[[Path], None]:
    def check(root: Path) -> None:
        text = (root / rel).read_text()
        for n in needles:
            assert n in text, f"{rel!r} should contain {n!r}; got:\n{text}"

    return check


def _file_lacks(rel: str, *needles: str) -> Callable[[Path], None]:
    def check(root: Path) -> None:
        text = (root / rel).read_text()
        for n in needles:
            assert n not in text, f"{rel!r} should not contain {n!r}; got:\n{text}"

    return check


def _all_of(*checks: Callable[[Path], None]) -> Callable[[Path], None]:
    def run(root: Path) -> None:
        for c in checks:
            c(root)

    return run


def _has_annotated_function(rel: str, fname: str) -> Callable[[Path], None]:
    def check(root: Path) -> None:
        tree = ast.parse((root / rel).read_text())
        fn = next(
            (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == fname),
            None,
        )
        assert fn is not None, f"function {fname} missing from {rel}"
        assert fn.returns is not None, f"{fname} has no return annotation"
        assert all(a.annotation is not None for a in fn.args.args), (
            f"{fname} args missing annotations"
        )

    return check


# ── tasks ─────────────────────────────────────────────────────────────────────

_TASKS: list[BenchTask] = [
    BenchTask(
        name="add_type_hints",
        files={
            "math_utils.py": textwrap.dedent("""\
                def add(a, b):
                    return a + b


                def subtract(a, b):
                    return a - b
                """),
        },
        prompt="Add type hints to both functions. Use int for parameters and return types.",
        check=_all_of(
            _has_annotated_function("math_utils.py", "add"),
            _has_annotated_function("math_utils.py", "subtract"),
        ),
    ),
    BenchTask(
        name="rename_function",
        files={
            "calc.py": textwrap.dedent("""\
                def compute(x):
                    return x * 2


                print(compute(5))
                """),
        },
        prompt="Rename the function `compute` to `double` everywhere in calc.py.",
        check=_all_of(
            _file_contains("calc.py", "def double", "double(5)"),
            _file_lacks("calc.py", "def compute", "compute(5)"),
        ),
    ),
    BenchTask(
        name="add_default_parameter",
        files={
            "greet.py": textwrap.dedent("""\
                def greet(name):
                    return f"Hello, {name}"
                """),
        },
        prompt='Add a `greeting` parameter to greet() with default value "Hello", and use it in the return string.',
        check=_file_contains("greet.py", "greeting=", '"Hello"'),
    ),
    BenchTask(
        name="add_docstring",
        files={
            "util.py": textwrap.dedent("""\
                def square(n):
                    return n * n
                """),
        },
        prompt='Add a one-line docstring to square() that says "Return n squared.".',
        check=_file_contains("util.py", '"""Return n squared.'),
    ),
    BenchTask(
        name="fix_off_by_one",
        files={
            "loop.py": textwrap.dedent("""\
                def first_n(items, n):
                    result = []
                    for i in range(n + 1):
                        result.append(items[i])
                    return result
                """),
        },
        prompt="Fix the off-by-one bug in first_n: the loop range should be range(n), not range(n + 1).",
        check=_all_of(
            _file_contains("loop.py", "range(n)"),
            _file_lacks("loop.py", "range(n + 1)", "range(n+1)"),
        ),
    ),
    BenchTask(
        name="add_empty_input_guard",
        files={
            "stats.py": textwrap.dedent("""\
                def mean(numbers):
                    return sum(numbers) / len(numbers)
                """),
        },
        prompt="Make mean() return 0 when given an empty list, instead of raising ZeroDivisionError.",
        check=_file_contains("stats.py", "if not numbers", "return 0"),
    ),
    BenchTask(
        name="replace_format_with_fstring",
        files={
            "fmt.py": textwrap.dedent("""\
                def greet(name, age):
                    return "Hello {}, you are {} years old".format(name, age)
                """),
        },
        prompt="Replace the .format() call with an f-string. Keep the same output.",
        check=_all_of(
            _file_contains("fmt.py", 'f"Hello {name}'),
            _file_lacks("fmt.py", ".format("),
        ),
    ),
    BenchTask(
        name="add_missing_import",
        files={
            "paths.py": textwrap.dedent("""\
                def home_config():
                    return Path.home() / ".config"
                """),
        },
        prompt="Add the missing `from pathlib import Path` import at the top of paths.py.",
        check=_file_contains("paths.py", "from pathlib import Path"),
    ),
    BenchTask(
        name="wrap_in_try_except",
        files={
            "parse.py": textwrap.dedent("""\
                import json


                def load(text):
                    return json.loads(text)
                """),
        },
        prompt="Wrap json.loads in try/except json.JSONDecodeError and return None on failure.",
        check=_file_contains("parse.py", "try:", "except json.JSONDecodeError", "return None"),
    ),
    BenchTask(
        name="remove_unused_import",
        files={
            "uses.py": textwrap.dedent("""\
                import os
                import sys


                def main():
                    print(sys.argv)
                """),
        },
        prompt="Remove the unused `import os` line.",
        check=_all_of(
            _file_lacks("uses.py", "import os"),
            _file_contains("uses.py", "import sys"),
        ),
    ),
    BenchTask(
        name="add_class_method",
        files={
            "user.py": textwrap.dedent("""\
                class User:
                    def __init__(self, name):
                        self.name = name
                """),
        },
        prompt="Add a method `greet(self)` on User that returns f'Hello, {self.name}'.",
        check=_file_contains("user.py", "def greet(self)", "Hello"),
    ),
    BenchTask(
        name="change_return_type",
        files={
            "convert.py": textwrap.dedent("""\
                def to_int(s):
                    return int(s)
                """),
        },
        prompt="Change to_int() to return None when the conversion fails (ValueError), instead of raising.",
        check=_file_contains("convert.py", "except", "return None"),
    ),
    BenchTask(
        name="convert_list_to_set",
        files={
            "dedup.py": textwrap.dedent("""\
                def unique(items):
                    result = []
                    for item in items:
                        if item not in result:
                            result.append(item)
                    return result
                """),
        },
        prompt="Replace the unique() body with a single line that returns a list built from set(items).",
        check=_all_of(
            _file_contains("dedup.py", "set(items)"),
            _file_lacks("dedup.py", "for item in items"),
        ),
    ),
    BenchTask(
        name="add_argument_validation",
        files={
            "div.py": textwrap.dedent("""\
                def divide(a, b):
                    return a / b
                """),
        },
        prompt="Raise ValueError('b must be non-zero') when b == 0, before the division.",
        check=_file_contains("div.py", "if b == 0", "ValueError", "non-zero"),
    ),
    BenchTask(
        name="extract_helper",
        files={
            "process.py": textwrap.dedent("""\
                def run(items):
                    cleaned = [s.strip().lower() for s in items if s]
                    print(cleaned)
                """),
        },
        prompt="Extract the list comprehension into a top-level helper `_clean(items)` that returns the cleaned list. Call it from run().",
        check=_file_contains("process.py", "def _clean(items)", "_clean(items)"),
    ),
]


# ── runner ────────────────────────────────────────────────────────────────────


@pytest.mark.llm
@pytest.mark.parametrize("task", _TASKS, ids=lambda t: t.name)
async def test_qwen_produces_applicable_patch(task: BenchTask, tmp_path: Path) -> None:
    runner = AsyncShellRunner()
    await runner.run(["git", "init", "-q"], cwd=str(tmp_path))
    await runner.run(["git", "config", "user.email", "bench@local"], cwd=str(tmp_path))
    await runner.run(["git", "config", "user.name", "bench"], cwd=str(tmp_path))

    for name, content in task.files.items():
        (tmp_path / name).write_text(content)
    await runner.run(["git", "add", "."], cwd=str(tmp_path))
    await runner.run(["git", "commit", "-q", "-m", "init"], cwd=str(tmp_path))

    llm = OpenAICompatibleAdapter(
        base_url=f"{_PROFILE.provider_base_url()}/v1",
        api_key=_PROFILE.api_key(),
        model=_PROFILE.model,
    )
    agent = StepAgent(llm=llm, cwd=tmp_path, config=_CONFIG)

    result = await agent.ask(task.prompt)
    assert result.edits, (
        f"model produced no edit blocks. raw reply:\n{result.reply[:600]}"
    )

    ok, err = apply_edits(result.edits, tmp_path)
    assert ok, f"apply_edits failed: {err}\n\n--- reply ---\n{result.reply[:800]}"

    task.check(tmp_path)


# ── multi-file navigation ────────────────────────────────────────────────────


@pytest.mark.llm
async def test_qwen_navigates_multi_file_project(tmp_path: Path) -> None:
    """v0.2 tool-loop check: 3-file project, agent sees only the map. Model
    must (a) pick the right file from the map and (b) read it via tool call
    before producing SEARCH/REPLACE."""
    (tmp_path / "main.py").write_text("from helpers import add\nprint(add(1, 2))\n")
    (tmp_path / "helpers.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / "README.md").write_text("# Demo\n")

    runner = AsyncShellRunner()
    await runner.run(["git", "init", "-q"], cwd=str(tmp_path))
    await runner.run(["git", "config", "user.email", "x@y"], cwd=str(tmp_path))
    await runner.run(["git", "config", "user.name", "x"], cwd=str(tmp_path))
    await runner.run(["git", "add", "."], cwd=str(tmp_path))
    await runner.run(["git", "commit", "-q", "-m", "i"], cwd=str(tmp_path))

    llm = OpenAICompatibleAdapter(
        base_url=f"{_PROFILE.provider_base_url()}/v1",
        api_key=_PROFILE.api_key(),
        model=_PROFILE.model,
    )
    agent = StepAgent(llm=llm, cwd=tmp_path, config=_CONFIG)

    result = await agent.ask(
        "Add type hints to helpers.py: parameters and return type should be int."
    )

    assert result.edits, f"no edits, raw reply:\n{result.reply[:600]}"
    assert all(e.path == "helpers.py" for e in result.edits), (
        f"model edited wrong file(s): {[e.path for e in result.edits]}"
    )

    ok, err = apply_edits(result.edits, tmp_path)
    assert ok, f"apply_edits failed: {err}"

    out = (tmp_path / "helpers.py").read_text()
    assert "int" in out and "->" in out
