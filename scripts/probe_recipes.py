"""Probe: lazy loading, multi-dir discovery, regression on existing scenarios.

Запуск: `source .venv/bin/activate && python scripts/probe_recipes.py`
Требует LM Studio на http://localhost:1234 с загруженной моделью.

Тестирует три вещи:
  1. Eager/lazy recipe injection — модель видит/не видит контент рецепта.
  2. Multi-dir discovery — project > user > built-in приоритет.
  3. Регрессия — ключевые сценарии из probe.py не сломались.

Стратегия маркера: рецепт содержит уникальный токен SCALPELPROBE42,
который модель может упомянуть ТОЛЬКО если рецепт попал в prompt.
В тренировочных данных qwen этого токена нет.
"""

from __future__ import annotations

import asyncio
import contextlib
import shutil
import tempfile
import textwrap
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from pathlib import Path

from code_scalpel.config import AgentConfig, AppConfig, ModelProfile
from code_scalpel.runtime import Runtime

_CONFIG = AppConfig(
    profiles={
        "local": ModelProfile(
            provider="lmstudio",
            model="qwen/qwen2.5-coder-14b",
            seed=42,
        )
    },
    agent=AgentConfig(max_files=200, max_file_lines=400),
)

MARKER = "SCALPELPROBE42"  # unique; absent from any real training corpus


# ── helpers ──────────────────────────────────────────────────────────────────


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


_REAL_PROJECT = Path(__file__).parent.parent


@contextlib.asynccontextmanager
async def _project_with_recipes(
    recipes: dict[str, str],
    *,
    with_real_code: bool = False,
) -> AsyncGenerator[Path, None]:
    """Temp dir acting as project root.  `recipes` maps filename → content.

    Pass `with_real_code=True` to copy the real project's source tree into
    the temp dir so the model has real files to navigate.  Needed for eager
    probes where an empty dir causes the model to use tools, get empty
    results, and ignore the recipe.  Copying is isolated — nothing is ever
    written back to the real project.
    """
    with tempfile.TemporaryDirectory(prefix="probe_recipes_") as tmp:
        cwd = Path(tmp)
        if with_real_code:
            for name in ("code_scalpel", "tests"):
                src = _REAL_PROJECT / name
                if src.exists():
                    shutil.copytree(src, cwd / name)
            for name in ("pyproject.toml", "CLAUDE.md"):
                src = _REAL_PROJECT / name
                if src.exists():
                    shutil.copy2(src, cwd / name)
        for name, body in recipes.items():
            _write(cwd / ".code-scalpel" / "recipes" / name, body)
        yield cwd


async def _ask(cwd: Path, task: str) -> str:
    runtime = Runtime(cwd=cwd, config=_CONFIG, with_memory=False)
    result = await runtime.ask(task, mode="ask")
    return result.reply


@dataclass
class Result:
    name: str
    ok: bool
    msg: str
    reply: str


# ── recipe probes ─────────────────────────────────────────────────────────────


async def probe_eager_always_surfaces() -> Result:
    """Eager recipe surfaces on every turn.

    Uses `with_real_code=True` so the model finds real project files when
    it calls list_files/read_file.  An empty dir causes tool calls to return
    nothing and the model errors out without touching the recipe.  The temp
    dir is a copy — nothing is written to the real project.
    """
    recipe = textwrap.dedent(f"""\
        ---
        name: _probe_eager
        load: eager
        ---

        Testing convention: always run pytest with `--run-id={MARKER}` (team standard).
    """)
    async with _project_with_recipes({"_probe_eager.md": recipe}, with_real_code=True) as cwd:
        reply = await _ask(cwd, "какие конвенции по запуску тестов в этом проекте?")
    ok = MARKER.lower() in reply.lower()
    return Result(
        "eager-always-surfaces",
        ok,
        f"marker {'found ✓' if ok else 'MISSING ✗'}",
        reply,
    )


async def probe_lazy_surfaces_on_keyword_match() -> Result:
    """Lazy recipe fires when task text contains a declared keyword."""
    recipe = textwrap.dedent(f"""\
        ---
        name: redis-guide
        load: lazy
        keywords: [redis, кеш]
        ---

        Redis convention: all cache keys must carry prefix {MARKER}:
        (mandatory team rule, never omit it).
    """)
    async with _project_with_recipes({"redis-guide.md": recipe}) as cwd:
        reply = await _ask(cwd, "как организовать кеширование в redis?")
    ok = MARKER.lower() in reply.lower()
    return Result(
        "lazy-surfaces-on-match",
        ok,
        f"marker {'found ✓' if ok else 'MISSING ✗'}",
        reply,
    )


async def probe_lazy_suppressed_on_no_match() -> Result:
    """Lazy recipe must NOT appear when task contains no matching keyword."""
    recipe = textwrap.dedent(f"""\
        ---
        name: redis-guide
        load: lazy
        keywords: [redis]
        ---

        Redis convention: all keys carry prefix {MARKER}: (team rule).
    """)
    async with _project_with_recipes({"redis-guide.md": recipe}) as cwd:
        reply = await _ask(cwd, "как написать unit-тест с pytest?")
    ok = MARKER.lower() not in reply.lower()
    return Result(
        "lazy-suppressed-on-no-match",
        ok,
        f"marker {'absent ✓' if ok else 'LEAKED into off-topic reply ✗'}",
        reply,
    )


async def probe_lazy_case_insensitive_match() -> Result:
    """Keyword match is case-insensitive — 'Redis' triggers keywords:[redis]."""
    recipe = textwrap.dedent(f"""\
        ---
        name: redis-guide
        load: lazy
        keywords: [redis]
        ---

        Redis rule: prefix all keys with {MARKER}: (team convention).
    """)
    async with _project_with_recipes({"redis-guide.md": recipe}) as cwd:
        reply = await _ask(cwd, "подключение к Redis — как настроить?")
    ok = MARKER.lower() in reply.lower()
    return Result(
        "lazy-case-insensitive-match",
        ok,
        f"marker {'found ✓' if ok else 'MISSING ✗'}",
        reply,
    )


async def probe_eager_and_lazy_both_surface() -> Result:
    """recipes_for_turn delivers eager + lazy-matched in one turn.

    Both recipes use natural technical content so the model includes
    the markers organically: a pytest flag (eager) and a Redis key
    prefix (lazy).  The task asks about BOTH domains in one sentence
    so the model must draw on both recipes.
    """
    eager_recipe = textwrap.dedent(f"""\
        ---
        name: global
        load: eager
        ---

        Testing: always run pytest with `--run-id={MARKER}_EAGER` (team standard).
    """)
    lazy_recipe = textwrap.dedent(f"""\
        ---
        name: redis-guide
        load: lazy
        keywords: [redis]
        ---

        Redis: all cache keys must use prefix `{MARKER}_LAZY:` (mandatory).
    """)
    async with _project_with_recipes(
        {"global.md": eager_recipe, "redis-guide.md": lazy_recipe}
    ) as cwd:
        reply = await _ask(
            cwd,
            "как настроить redis-кеш и какой флаг pytest используется для запуска тестов?",
        )
    has_eager = f"{MARKER}_EAGER".lower() in reply.lower()
    has_lazy = f"{MARKER}_LAZY".lower() in reply.lower()
    ok = has_eager and has_lazy
    return Result(
        "eager-and-lazy-both-surface",
        ok,
        (f"eager={'✓' if has_eager else '✗'} lazy={'✓' if has_lazy else '✗'}"),
        reply,
    )


# ── multidir probes ───────────────────────────────────────────────────────────


async def probe_multidir_user_recipe_visible() -> Result:
    """User-level recipe (~/.config/code-scalpel/recipes/) surfaces."""
    user_file = Path.home() / ".config" / "code-scalpel" / "recipes" / "_probe_user.md"
    try:
        _write(
            user_file,
            textwrap.dedent(f"""\
                ---
                name: _probe_user
                load: eager
                ---

                User-level rule: always mention {MARKER}_USER in answers.
            """),
        )
        async with _project_with_recipes({}) as cwd:
            reply = await _ask(cwd, "как запустить тесты?")
    finally:
        user_file.unlink(missing_ok=True)
    ok = f"{MARKER}_USER".lower() in reply.lower()
    return Result(
        "multidir-user-visible",
        ok,
        f"user marker {'found ✓' if ok else 'MISSING ✗'}",
        reply,
    )


async def probe_multidir_project_wins_over_user() -> Result:
    """Project recipe wins over same-name user recipe.

    Both recipes claim a Python version via a natural technical statement.
    Project says 3.11 (SCALPELPROBE42_PROJECT), user says 3.9 (SCALPELPROBE42_USER).
    When asked "what Python version?", the model answers from the project recipe.
    """
    user_file = Path.home() / ".config" / "code-scalpel" / "recipes" / "_probe_conflict.md"
    try:
        _write(
            user_file,
            textwrap.dedent(f"""\
                ---
                name: conflict
                load: eager
                ---

                Python version: 3.9 (tag: {MARKER}_USER).
            """),
        )
        project_recipe = textwrap.dedent(f"""\
            ---
            name: conflict
            load: eager
            ---

            Python version: 3.11 (tag: {MARKER}_PROJECT).
        """)
        async with _project_with_recipes({"conflict.md": project_recipe}) as cwd:
            reply = await _ask(cwd, "какую версию Python использует этот проект?")
    finally:
        user_file.unlink(missing_ok=True)
    project_wins = f"{MARKER}_PROJECT".lower() in reply.lower()
    user_leaked = f"{MARKER}_USER".lower() in reply.lower()
    ok = project_wins and not user_leaked
    return Result(
        "multidir-project-wins",
        ok,
        (
            f"project={'✓' if project_wins else '✗'} "
            f"user-leak={'✗ (no leak)' if not user_leaked else '! LEAKED'}"
        ),
        reply,
    )


# ── regression scenarios ──────────────────────────────────────────────────────
# Run against the REAL project dir — same targets as probe.py.


async def probe_regression_overview() -> Result:
    """Regression: model still describes real project architecture."""
    runtime = Runtime(cwd=Path("."), config=_CONFIG, with_memory=False)
    result = await runtime.ask("Дай общее описание архитектуры этого проекта одним абзацем.")
    reply = result.reply
    ok = any(kw in reply.lower() for kw in ("code-scalpel", "tui", "агент", "agent"))
    return Result(
        "regression-overview",
        ok,
        "architecture terms found ✓" if ok else "no architecture terms ✗",
        reply,
    )


async def probe_regression_nonexistent_symbol() -> Result:
    """Regression: model admits when asked for non-existent symbol."""
    runtime = Runtime(cwd=Path("."), config=_CONFIG, with_memory=False)
    result = await runtime.ask("Где в проекте реализована функция quick_sort?")
    reply = result.reply
    ok = any(kw in reply.lower() for kw in ("не", "no such", "not found", "нет"))
    return Result(
        "regression-ask-nonexistent",
        ok,
        "correctly denied ✓" if ok else "may have hallucinated ✗",
        reply,
    )


async def probe_regression_recipes_dont_break_real_project() -> Result:
    """Regression: recipes_for_turn injection doesn't break real-project turns.

    The real project has no .code-scalpel/recipes/ by default, so this
    verifies an empty-recipes turn still produces a coherent answer.
    Check is intentionally broad — any mention of the agent, session,
    LLM, or processing terms counts.  We are testing that the turn
    wasn't broken, not that the model named a specific file.
    """
    runtime = Runtime(cwd=Path("."), config=_CONFIG, with_memory=False)
    result = await runtime.ask("Как идёт обработка от ввода пользователя до вызова LLM?")
    reply = result.reply
    ok = any(
        kw in reply.lower()
        for kw in (
            "stepagent",
            "scalpelapp",
            "agent",
            "session",
            "runtime",
            "llm",
            "prepare",
            "модул",
            "обработк",
            "вызов",
            "turn",
        )
    )
    return Result(
        "regression-real-project-flow",
        ok,
        "relevant terms found ✓" if ok else "model refused or off-topic ✗",
        reply,
    )


# ── runner ────────────────────────────────────────────────────────────────────

RECIPE_PROBES = [
    probe_eager_always_surfaces,
    probe_lazy_surfaces_on_keyword_match,
    probe_lazy_suppressed_on_no_match,
    probe_lazy_case_insensitive_match,
    probe_eager_and_lazy_both_surface,
    probe_multidir_user_recipe_visible,
    probe_multidir_project_wins_over_user,
]

REGRESSION_PROBES = [
    probe_regression_overview,
    probe_regression_nonexistent_symbol,
    probe_regression_recipes_dont_break_real_project,
]


async def _run_group(title: str, probes: list) -> int:  # type: ignore[type-arg]
    print(f"\n{'─' * 72}")
    print(f"  {title}")
    print(f"{'─' * 72}")
    passed = 0
    for fn in probes:
        print(f"\n[{fn.__name__.replace('probe_', '')}]")
        try:
            r: Result = await fn()
        except Exception as e:
            print(f"  ✗ ERROR: {type(e).__name__}: {e}")
            continue
        mark = "✓" if r.ok else "✗"
        print(f"  {mark} {r.msg}")
        head = textwrap.shorten(r.reply.replace("\n", " "), 120, placeholder="…")
        print(f"     reply: {head!r}")
        if r.ok:
            passed += 1
    return passed


async def main() -> None:
    total_probes = len(RECIPE_PROBES) + len(REGRESSION_PROBES)
    print("=" * 72)
    print("RECIPE PROBE — lazy / eager / multidir + regression")
    print("target: qwen2.5-coder-14b @ http://localhost:1234")
    print("=" * 72)

    rp = await _run_group("RECIPE PROBES (новые фичи)", RECIPE_PROBES)
    rr = await _run_group("REGRESSION (существующие сценарии)", REGRESSION_PROBES)

    total = rp + rr
    print(f"\n{'=' * 72}")
    print(
        f"RESULT: {total}/{total_probes} passed"
        f"  (recipes: {rp}/{len(RECIPE_PROBES)}"
        f"  regression: {rr}/{len(REGRESSION_PROBES)})"
    )
    print("=" * 72)


if __name__ == "__main__":
    asyncio.run(main())
