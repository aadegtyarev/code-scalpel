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

    result = await agent.ask(task.prompt, mode="code")
    assert result.edits, f"model produced no edit blocks. raw reply:\n{result.reply[:600]}"

    ok, err = apply_edits(result.edits, tmp_path)
    assert ok, f"apply_edits failed: {err}\n\n--- reply ---\n{result.reply[:800]}"

    task.check(tmp_path)


# ── behavioral checks ────────────────────────────────────────────────────────


def _make_agent(cwd: Path) -> StepAgent:
    llm = OpenAICompatibleAdapter(
        base_url=f"{_PROFILE.provider_base_url()}/v1",
        api_key=_PROFILE.api_key(),
        model=_PROFILE.model,
    )
    return StepAgent(llm=llm, cwd=cwd, config=_CONFIG)


@pytest.mark.llm
async def test_qwen_history_remembers_previous_turn(tmp_path: Path) -> None:
    """Second turn should see the first one. Asks a value, then asks to
    reuse it — the model can only succeed if history was sent."""
    (tmp_path / "hello.py").write_text("def hello():\n    pass\n")
    agent = _make_agent(tmp_path)

    await agent.ask("Remember the number 4242. Just acknowledge, don't write any code yet.")
    result = await agent.ask("What number did I just ask you to remember?")

    assert "4242" in result.reply, (
        f"model didn't recall the value across turns:\n{result.reply[:400]}"
    )


@pytest.mark.llm
async def test_qwen_history_three_turn_topic_continuity(tmp_path: Path) -> None:
    """Three turns about the same topic — model must stitch them together."""
    (tmp_path / "stub.py").write_text("# noop\n")
    agent = _make_agent(tmp_path)

    await agent.ask("I'm thinking about adopting a pet. Just say 'OK', no advice yet.")
    await agent.ask("Specifically I like fluffy ones. Still just acknowledge.")
    result = await agent.ask("Given that, what pet would you suggest?")
    # No specific word required, but model must mention a fluffy animal
    lower = result.reply.lower()
    assert any(kw in lower for kw in ("cat", "dog", "rabbit", "кош", "соба", "кролик", "хом")), (
        f"third turn ignored earlier context:\n{result.reply[:400]}"
    )


@pytest.mark.llm
async def test_qwen_native_tool_call_is_structured(tmp_path: Path) -> None:
    """Native function calling: the response carries tool_calls in the
    structured field, NOT inside the text body."""
    (tmp_path / "hello.py").write_text("def hello():\n    return 1\n")
    agent = _make_agent(tmp_path)

    # Intercept chat() to see exactly what comes back from LM Studio
    real_chat = agent._llm.chat
    seen: list[object] = []

    async def spy(messages: list[dict[str, object]], **kw: object) -> object:
        resp = await real_chat(messages, **kw)  # type: ignore[arg-type]
        seen.append(resp)
        return resp

    agent._llm.chat = spy  # type: ignore[assignment]

    await agent.ask("Read hello.py and tell me one sentence about it.")

    # At least one response had structured tool_calls, none used <TOOL: ...> text
    any_native = any(getattr(r, "tool_calls", ()) for r in seen)
    any_text_tool = any("<TOOL:" in getattr(r, "content", "") for r in seen)
    assert any_native, "model didn't emit any native tool_calls"
    assert not any_text_tool, "model fell back to text-based <TOOL: ...> format"


@pytest.mark.llm
async def test_qwen_history_after_tool_call_keeps_topic(tmp_path: Path) -> None:
    """Turn 1: model reads a file via tool. Turn 2: ask about that file.
    Model must still know what was discussed."""
    (tmp_path / "magic.py").write_text("MAGIC_NUMBER = 7777\n")
    agent = _make_agent(tmp_path)

    await agent.ask("Read magic.py and tell me what constant it defines.")
    result = await agent.ask("What was the value of that constant?")

    assert "7777" in result.reply, (
        f"model lost the constant value across turns:\n{result.reply[:400]}"
    )


@pytest.mark.llm
async def test_qwen_plain_text_for_non_coding_question(tmp_path: Path) -> None:
    """A conversational question should NOT produce SEARCH/REPLACE blocks."""
    (tmp_path / "x.py").write_text("x = 1\n")
    agent = _make_agent(tmp_path)
    result = await agent.ask("In one sentence: what does this project do?")
    assert not result.edits, (
        f"model emitted edit blocks for a casual question:\n{result.reply[:400]}"
    )
    assert len(result.reply.strip()) > 10


@pytest.mark.llm
async def test_qwen_does_not_claim_to_be_claude_or_openai(tmp_path: Path) -> None:
    """Identity pin: ask 'who are you' — model must NOT claim a commercial AI."""
    (tmp_path / "x.py").write_text("# noop\n")
    agent = _make_agent(tmp_path)
    result = await agent.ask("Who are you? One sentence.")
    lower = result.reply.lower()
    assert "anthropic" not in lower, f"model claimed Anthropic:\n{result.reply[:400]}"
    assert "openai" not in lower, f"model claimed OpenAI:\n{result.reply[:400]}"
    assert "claude" not in lower, f"model claimed Claude:\n{result.reply[:400]}"
    assert "chatgpt" not in lower and "gpt" not in lower, (
        f"model claimed GPT:\n{result.reply[:400]}"
    )


@pytest.mark.llm
async def test_qwen_replies_in_russian_when_asked_in_russian(tmp_path: Path) -> None:
    """Bench harness doesn't go through the TUI's language pinning, so we
    add the hint here the same way ScalpelApp._run_step does."""
    (tmp_path / "x.py").write_text("x = 1\n")
    agent = _make_agent(tmp_path)
    result = await agent.ask(
        "Объясни одним предложением что делает этот файл.\n\n(Reply in Russian.)"
    )
    # Pretty robust check: response must contain Cyrillic characters
    has_cyrillic = any("Ѐ" <= ch <= "ӿ" for ch in result.reply)
    assert has_cyrillic, f"model replied without Cyrillic:\n{result.reply[:400]}"


@pytest.mark.llm
async def test_qwen_creates_new_file_via_empty_search(tmp_path: Path) -> None:
    """Asking to create a new file should produce an empty SEARCH block."""
    (tmp_path / "existing.py").write_text("x = 1\n")
    agent = _make_agent(tmp_path)
    result = await agent.ask(
        "Create a new file `greet.py` containing exactly: def greet(): print('hi')",
        mode="code",
    )
    assert result.edits, f"no edits:\n{result.reply[:400]}"

    ok, err = apply_edits(result.edits, tmp_path)
    assert ok, f"apply failed: {err}"
    assert (tmp_path / "greet.py").exists()
    assert "def greet" in (tmp_path / "greet.py").read_text()


@pytest.mark.xfail(
    reason="System prompt only documents read_file. Model knows grep exists in our "
    "code but isn't told it can call it. Will pass once v0.3 switches to native "
    "function calling that exposes all tools via the API.",
    strict=False,
)
@pytest.mark.llm
async def test_qwen_uses_grep_when_asked_to_find(tmp_path: Path) -> None:
    """When asked 'where in the project is X used', model should reach for
    grep rather than reading every file."""
    (tmp_path / "main.py").write_text("from helpers import compute\nprint(compute(1))\n")
    (tmp_path / "helpers.py").write_text("def compute(x):\n    return x * 2\n")
    (tmp_path / "other.py").write_text("x = 1\n")
    agent = _make_agent(tmp_path)

    # Intercept the LLM to see what tool calls are made
    real_chat = agent._llm.chat
    tool_calls_seen: list[str] = []

    async def spy_chat(messages: list[dict[str, str]], **kw: object) -> object:
        resp = await real_chat(messages, **kw)  # type: ignore[arg-type]
        tool_calls_seen.append(resp.content)
        for tc in resp.tool_calls:
            tool_calls_seen.append(f"<TOOL:{tc.name}>{tc.arguments}</TOOL>")
        return resp

    agent._llm.chat = spy_chat  # type: ignore[assignment]

    await agent.ask(
        "Where in the project is the function `compute` used? Don't change anything, just tell me."
    )
    combined = "\n".join(tool_calls_seen)
    # Either grep was called, or read_file on multiple files. Both are
    # reasonable, but grep is the smarter choice.
    assert "<TOOL: grep>" in combined or "<TOOL: read_file>" in combined, (
        f"model didn't use any tool to look:\n{combined[:600]}"
    )


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
        "Add type hints to helpers.py: parameters and return type should be int.",
        mode="code",
    )

    assert result.edits, f"no edits, raw reply:\n{result.reply[:600]}"
    assert all(e.path == "helpers.py" for e in result.edits), (
        f"model edited wrong file(s): {[e.path for e in result.edits]}"
    )

    ok, err = apply_edits(result.edits, tmp_path)
    assert ok, f"apply_edits failed: {err}"

    out = (tmp_path / "helpers.py").read_text()
    assert "int" in out and "->" in out


# ── grounding / anti-hallucination ───────────────────────────────────────────
# These cases lock in the prompt's "do not make things up" clause. They
# exist because of the 2026-05-11 regression where the model invented
# AgentState.summary_line() — a method that doesn't exist — when asked
# where summarization lived in the project.


_ADMITS_MISSING = (
    # English
    "doesn't exist",
    "does not exist",
    "not found",
    "no such",
    "couldn't find",
    "can't find",
    "i don't see",
    "isn't in",
    "is not in",
    "not present",
    "no method",
    "no function",
    # Russian — order matters less, all are substrings
    "не существует",
    "нет такого",
    "не найден",
    "не найдено",
    "не вижу",
    "отсутствует",
    "нет метода",
    "нет функции",
    "нет в проекте",
    "там нет",
    "тут нет",
    "не нашёл",
    "не нашел",
)


def _admits_missing(reply: str) -> bool:
    low = reply.lower()
    return any(phrase in low for phrase in _ADMITS_MISSING)


@pytest.mark.llm
async def test_qwen_admits_missing_method(tmp_path: Path) -> None:
    """Asked about a method that doesn't exist, model must say so — not
    fabricate a plausible name."""
    (tmp_path / "store.py").write_text(
        "class Cache:\n"
        "    def get(self, key):\n        return None\n"
        "    def set(self, k, v):\n        pass\n"
    )
    agent = _make_agent(tmp_path)
    result = await agent.ask("Где в проекте реализован метод .summarize() у класса Cache?")
    assert _admits_missing(result.reply), (
        f"model didn't admit summarize() is missing:\n{result.reply[:500]}"
    )


@pytest.mark.llm
async def test_qwen_reads_file_before_showing_code(tmp_path: Path) -> None:
    """Asked to SHOW code, the model must ground via read_file/grep rather
    than reproducing from memory based on the symbol name."""
    (tmp_path / "lib.py").write_text("def add(a, b):\n    return a + b\n")
    agent = _make_agent(tmp_path)

    real_chat = agent._llm.chat
    tools_seen: list[str] = []

    async def spy(messages: list[dict[str, object]], **kw: object) -> object:
        resp = await real_chat(messages, **kw)  # type: ignore[arg-type]
        for tc in resp.tool_calls:
            tools_seen.append(tc.name)
        return resp

    agent._llm.chat = spy  # type: ignore[assignment]
    await agent.ask("Покажи код функции add из lib.py")
    assert any(t in tools_seen for t in ("read_file", "grep")), (
        f"model produced code without reading the file. tools_seen={tools_seen}"
    )


@pytest.mark.llm
async def test_qwen_does_not_invent_class_method_from_intent(tmp_path: Path) -> None:
    """The exact bug from 2026-05-11: AgentState exists but summary_line
    doesn't. Asking 'find where summarization is implemented' must NOT
    confabulate. Either the model says it's not there, or it names a real
    symbol that DOES exist."""
    import textwrap

    (tmp_path / "state.py").write_text(
        textwrap.dedent("""\
            from pydantic import BaseModel


            class AgentState(BaseModel):
                step_id: int = 0
                dirty_patch: bool = False

                def save(self, root):
                    pass

                @classmethod
                def load(cls, root):
                    pass

                @classmethod
                def reset(cls, root):
                    pass
        """)
    )
    agent = _make_agent(tmp_path)
    result = await agent.ask("найди где в проекте суммаризация контента")

    # The fabrications observed in the bug
    forbidden = ("summary_line", "summarize_content", "summarize_state")
    low = result.reply.lower()
    invented = [w for w in forbidden if w in low]
    if invented:
        assert _admits_missing(result.reply), (
            f"model invented {invented} without flagging it as missing:\n{result.reply[:600]}"
        )


@pytest.mark.llm
async def test_qwen_cites_file_when_pointing(tmp_path: Path) -> None:
    """When answering 'where is X', a grounded reply names the path that
    the model can see in the map. Substring check for the actual file."""
    (tmp_path / "math_ops.py").write_text("def compute(x, y):\n    return x + y\n")
    (tmp_path / "other.py").write_text("# unrelated\n")
    agent = _make_agent(tmp_path)
    result = await agent.ask("Где определена функция compute?")
    assert "math_ops.py" in result.reply, (
        f"reply didn't cite the actual file path:\n{result.reply[:400]}"
    )
