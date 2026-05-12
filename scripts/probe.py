"""Live probe: типовые сценарии использования агента на реальном проекте.

Запуск: `source .venv/bin/activate && python scripts/probe.py`
Требует LM Studio на http://localhost:1234 с загруженной моделью.

Назначение: то что LLM-бенч НЕ покрывает — живое многоходовое
общение, кейсы которые юзер реально встречает каждый день. Это
инструмент **глаза**: запустил — смотри что модель отвечает на
твоих типовых задачах сегодня.

Бенч даёт булеан pass/fail на изолированных fixture'ах. Probe
показывает поведение на твоём ЖИВОМ проекте — где map содержит
все 500+ символов, history накапливается, и модель должна вести
себя как ассистент, а не сдавать кейсы.
"""

from __future__ import annotations

import asyncio
import textwrap
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from code_scalpel.agent import StepAgent
from code_scalpel.config import AgentConfig, AppConfig, ModelProfile
from code_scalpel.llm.adapter import OpenAICompatibleAdapter

_CONFIG = AppConfig(
    profiles={
        "local": ModelProfile(
            provider="lmstudio",
            model="qwen/qwen2.5-coder-14b",
            # No explicit temperature — use the per-mode defaults from
            # ModeTemperatures (ask=0.7 etc.). Pinning to 0.1 here used
            # to mask the deterministic-refusal pattern the bump fixes.
            seed=42,
        )
    },
    agent=AgentConfig(max_files=200, max_file_lines=400),
)


@dataclass
class Scenario:
    name: str
    description: str
    turns: list[str]
    check: Callable[[list[str]], tuple[bool, str]]


def _contains(needle: str, *, turn: int = 0) -> Callable[[list[str]], tuple[bool, str]]:
    """Pass if the needle appears (case-insensitive) in the specified turn."""

    def go(replies: list[str]) -> tuple[bool, str]:
        target = replies[turn].lower()
        if needle.lower() in target:
            return True, f"'{needle}' found in T{turn + 1}"
        return False, f"'{needle}' missing from T{turn + 1}: {replies[turn][:80]!r}"

    return go


def _contains_any(*needles: str, turn: int = 0) -> Callable[[list[str]], tuple[bool, str]]:
    def go(replies: list[str]) -> tuple[bool, str]:
        target = replies[turn].lower()
        for n in needles:
            if n.lower() in target:
                return True, f"'{n}' found in T{turn + 1}"
        return False, f"none of {needles} in T{turn + 1}: {replies[turn][:80]!r}"

    return go


def _no_repeat(replies: list[str]) -> tuple[bool, str]:
    """Consecutive turn heads must differ — repeat = model stuck."""
    for i in range(1, len(replies)):
        prev_head = replies[i - 1][:60].strip().lower()
        curr_head = replies[i][:60].strip().lower()
        if prev_head == curr_head:
            return False, f"T{i + 1} repeats T{i}: {replies[i][:60]!r}"
    return True, "no consecutive-turn repeats"


# Each scenario is a real user-shaped session against the LIVE project.
SCENARIOS = [
    Scenario(
        name="overview",
        description="High-level architecture description — map alone enough",
        turns=["Дай общее описание архитектуры этого проекта одним абзацем."],
        check=_contains_any("code-scalpel", "tui", "агент"),
    ),
    Scenario(
        name="flow",
        description="Trace the flow — needs imports + reasoning across files",
        turns=[
            "Как идёт обработка от ввода пользователя до вызова LLM? "
            "Назови ключевые модули по порядку."
        ],
        # Reply must mention at least one anchor module/class from the
        # actual code path. We accept the obvious names (StepAgent /
        # ScalpelApp) but also the file paths since models often quote
        # paths from list_files output verbatim.
        check=_contains_any("stepagent", "scalpelapp", "agent.py", "tui/app.py", "_chat_loop"),
    ),
    Scenario(
        name="classifier-usage",
        description="'Is classifier.py used in main flow?' — needs grep, NOT in agent.py imports",
        turns=["Используется ли classifier.py где-то в основном потоке агента?"],
        check=_contains_any("не используется", "только в тестах", "not used"),
    ),
    Scenario(
        name="misattribution-repro",
        description="2026-05-11 bug: compact vs mark_compacted — model must pick the real one",
        turns=["Где в проекте контекст сжимается?"],
        # Accept any of the real compression-related symbols/files —
        # context_compress.py, compact(), mark_compacted, "сжатие".
        # The earlier "compact" substring was too narrow: a correct
        # answer in Russian using "сжимается / context_compress" was
        # marked failing.
        check=_contains_any("compact", "сжима", "context_compress"),
    ),
    Scenario(
        name="short-followup",
        description="Sonet bug: long T1, short T2 clarification — model must NOT repeat T1",
        turns=[
            "как добавить в проект работу с антропик моделями?",
            "Sonnet",
        ],
        check=_no_repeat,
    ),
    Scenario(
        name="ask-nonexistent",
        description="Method that doesn't exist — must admit, not invent",
        turns=["Где в проекте реализована функция quick_sort?"],
        check=_contains_any("не", "no such", "not found"),
    ),
    Scenario(
        name="show-method-body",
        description="Show body of a real method — must read_file, not guess",
        turns=["Покажи тело метода mark_compacted из Session"],
        # We just want a non-empty answer mentioning the method by name
        check=_contains("mark_compacted"),
    ),
    Scenario(
        name="task-engages-with-project",
        description="'найди место чтобы ...' must trigger tool calls and engage with real files",
        turns=["найди место, чтобы в футер вывести текущее системное время"],
        # Pass if the reply mentions a real project file or method —
        # implies the model actually grep'd / listed / read.
        check=_contains_any("footer", "status", ".py", "session"),
    ),
    Scenario(
        name="plan-mode",
        description="Plan mode: produce TASKS.md structure",
        turns=[],  # set below — plan mode needs explicit mode pass
        check=_contains("## T001"),
    ),
]


async def run_scenario(sc: Scenario, *, mode: str = "ask") -> tuple[bool, str, list[str]]:
    llm = OpenAICompatibleAdapter(
        base_url="http://localhost:1234/v1",
        api_key="lm-studio",
        model="qwen/qwen2.5-coder-14b",
    )
    agent = StepAgent(llm=llm, cwd=Path("."), config=_CONFIG)
    replies: list[str] = []
    for prompt in sc.turns:
        result = await agent.ask(prompt, mode=mode)
        replies.append(result.reply)
    ok, msg = sc.check(replies)
    return ok, msg, replies


async def main() -> None:
    # Plan-mode scenario needs an actual prompt — assigned here so the
    # static list above stays readable.
    plan_scenario = SCENARIOS[-1]
    plan_scenario.turns = [
        "Спланируй задачу: добавить /history slash для просмотра истории сессии."
    ]

    print("=" * 72)
    print("LIVE PROBE — типовые сценарии использования")
    print("target: qwen2.5-coder-14b @ http://localhost:1234")
    print("=" * 72)

    passed = 0
    for sc in SCENARIOS:
        print(f"\n[{sc.name}] {sc.description}")
        mode = "plan" if sc.name == "plan-mode" else "ask"
        try:
            ok, msg, replies = await run_scenario(sc, mode=mode)
        except Exception as e:
            print(f"  ✗ ERROR: {type(e).__name__}: {e}")
            continue
        mark = "✓" if ok else "✗"
        print(f"  {mark} {msg}")
        for i, r in enumerate(replies, 1):
            head = textwrap.shorten(r.replace("\n", " "), 110, placeholder="…")
            print(f"     T{i}: {head}")
        if ok:
            passed += 1

    print("\n" + "=" * 72)
    print(f"RESULT: {passed}/{len(SCENARIOS)} passed")
    print("=" * 72)


if __name__ == "__main__":
    asyncio.run(main())
