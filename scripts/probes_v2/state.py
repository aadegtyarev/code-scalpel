"""Пути, форматы артефактов, утилиты для probe-run папки.

Все писатели и читатели артефактов проходят через эти функции,
чтобы структура run-dir оставалась консистентной."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROBE_RUNS_ROOT = Path("docs/article/probe-runs")
FIXTURES_ROOT = Path("scripts/probes_v2/fixtures")
SCENARIOS_ROOT = Path("scripts/probes_v2/scenarios")


@dataclass(frozen=True)
class RunPaths:
    """All artifact file paths for a single run-id. Built from
    run-dir once at start; passed everywhere instead of recomputing."""

    run_dir: Path

    @property
    def meta_json(self) -> Path:
        return self.run_dir / "meta.json"

    @property
    def scenario_md(self) -> Path:
        return self.run_dir / "scenario.md"

    @property
    def fixture_tar(self) -> Path:
        return self.run_dir / "fixture_initial.tar.gz"

    @property
    def chat_jsonl(self) -> Path:
        return self.run_dir / "chat.jsonl"

    @property
    def tools_jsonl(self) -> Path:
        return self.run_dir / "tools.jsonl"

    @property
    def agent_plan_md(self) -> Path:
        return self.run_dir / "agent_plan.md"

    @property
    def user_plan_md(self) -> Path:
        return self.run_dir / "user_plan.md"

    @property
    def final_tree(self) -> Path:
        return self.run_dir / "final_tree"

    @property
    def metrics_json(self) -> Path:
        return self.run_dir / "metrics.json"

    @property
    def timing_jsonl(self) -> Path:
        """Жёрнальный формат, append-only — один event per line.
        JSON-массив был бы concurrency-safer для редких писаний, но
        timing пишется при каждом step → проще append."""
        return self.run_dir / "timing.jsonl"

    @property
    def verdict_json(self) -> Path:
        return self.run_dir / "verdict.json"

    @property
    def evaluation_md(self) -> Path:
        return self.run_dir / "evaluation.md"

    @property
    def notes_md(self) -> Path:
        return self.run_dir / "notes.md"

    @property
    def figures(self) -> Path:
        return self.run_dir / "figures"

    @property
    def daemon_info(self) -> Path:
        """Где демон пишет PID + порт. Точка в имени —
        не попадает в основной артефакт-листинг."""
        return self.run_dir / ".daemon.json"

    @property
    def workdir(self) -> Path:
        """Tmp рабочая копия fixture'ы (вне репо). Удаляется на
        finalize. Tar.gz содержимого этой папки → fixture_tar."""
        return self.run_dir / ".workdir"


def make_run_id(scenario: str, project: str, git_sha: str, now: datetime | None = None) -> str:
    """`<scenario>-<project>-<sha7>-<YYYYMMDD-HHMMSS>`."""
    ts = (now or datetime.now(UTC)).strftime("%Y%m%d-%H%M%S")
    return f"{scenario}-{project}-{git_sha[:7]}-{ts}"


def current_git_sha(cwd: Path | None = None) -> str:
    """`git rev-parse HEAD`, или `unknown` если не репо / git
    не отвечает. Используем для run-id и для meta.json."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    if out.returncode != 0:
        return "unknown"
    return out.stdout.strip()


def git_is_dirty(cwd: Path | None = None) -> bool:
    """True если есть uncommitted changes. `git status --porcelain`
    — пустой stdout = чисто. Используется в meta.json как сигнал
    «прогон не полностью воспроизводим через git checkout <sha>»."""
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return bool(out.stdout.strip())


def git_remote_url(cwd: Path | None = None) -> str | None:
    """Origin URL (для построения commit-link'а). None если нет
    remote или git не отвечает. Нормализуем `git@github.com:foo/bar.git`
    → `https://github.com/foo/bar`."""
    try:
        out = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    raw = out.stdout.strip()
    if not raw:
        return None
    if raw.startswith("git@github.com:"):
        return "https://github.com/" + raw.removeprefix("git@github.com:").removesuffix(".git")
    if raw.startswith("https://") and raw.endswith(".git"):
        return raw.removesuffix(".git")
    return raw


def write_placeholder_artifacts(paths: RunPaths) -> None:
    """Создаёт все артефакты-заглушки в `run_dir`. Каждый файл
    существует с самого старта, заполняется по ходу. Если что-то
    остаётся незаполненным к finalize — это «N/A», не «забыли»."""
    paths.run_dir.mkdir(parents=True, exist_ok=True)
    paths.figures.mkdir(exist_ok=True)
    paths.final_tree.mkdir(exist_ok=True)

    if not paths.chat_jsonl.exists():
        paths.chat_jsonl.write_text("")
    if not paths.tools_jsonl.exists():
        paths.tools_jsonl.write_text("")
    if not paths.timing_jsonl.exists():
        paths.timing_jsonl.write_text("")
    if not paths.metrics_json.exists():
        paths.metrics_json.write_text(json.dumps(default_metrics(), indent=2) + "\n")
    if not paths.verdict_json.exists():
        paths.verdict_json.write_text(json.dumps(default_verdict(), indent=2) + "\n")
    if not paths.agent_plan_md.exists():
        paths.agent_plan_md.write_text(_PLACEHOLDER_AGENT_PLAN)
    if not paths.user_plan_md.exists():
        paths.user_plan_md.write_text(_PLACEHOLDER_USER_PLAN)
    if not paths.evaluation_md.exists():
        paths.evaluation_md.write_text(_PLACEHOLDER_EVALUATION)
    if not paths.notes_md.exists():
        paths.notes_md.write_text(_PLACEHOLDER_NOTES)


def default_metrics() -> dict[str, Any]:
    return {
        "user_turns": 0,
        "agent_llm_requests": 0,
        "prompt_tokens_total": 0,
        "completion_tokens_total": 0,
        "prompt_tokens_peak": 0,
        "tool_calls_total": 0,
        "tool_calls_by_name": {},
        "retries": 0,
        "commits_landed": 0,
        "wall_time_sec": 0.0,
    }


def default_verdict() -> dict[str, Any]:
    return {
        "scenario": None,
        "pass_score": 0,
        "pass_max": 0,
        "criteria": {},
        "ended_reason": None,
    }


def append_jsonl(path: Path, event: dict[str, Any]) -> None:
    """Атомарно дописывает одну JSON-строку. fsync не делаем —
    crash safety здесь best-effort, основной сигнал — git
    commit после finalize."""
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")


def update_json(path: Path, update: dict[str, Any]) -> None:
    """Read-modify-write для metrics/verdict. Не пытаемся быть
    конкурентно-безопасными — runner однопоточный."""
    current = json.loads(path.read_text()) if path.exists() else {}
    current.update(update)
    path.write_text(json.dumps(current, indent=2) + "\n")


def utc_now() -> str:
    """ISO8601 timestamp с `Z` — единый формат для timing/chat/tools."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


_PLACEHOLDER_AGENT_PLAN = """# Agent plan (TASKS.md от scalpel'а)

_(в этом сценарии план не генерировался, или прогон ещё не дошёл до планирования)_
"""

_PLACEHOLDER_USER_PLAN = """# User plan

## Что я хочу добиться
_(заполнить ДО первого turn'а)_

## Как буду себя вести (стиль)
По [user_tone_of_voice](../../../../../home/adegtyarev/.claude/projects/-home-adegtyarev-Develop-Hobby-code-scalpel/memory/user_tone_of_voice.md).

## Что НЕ говорю
_(например: не подсказываю где баг — пусть scalpel сам найдёт)_

## Reference replies (если планировал заранее)
_(опционально)_
"""

_PLACEHOLDER_EVALUATION = """# Evaluation

_(заполнить после finalize по шаблону из scripts/probes_v2/PROTOCOL.md)_

## One-liner
_(пока не написано)_
"""

_PLACEHOLDER_NOTES = """# Notes

_(заметок по ходу пока не было)_
"""


__all__ = [
    "FIXTURES_ROOT",
    "PROBE_RUNS_ROOT",
    "SCENARIOS_ROOT",
    "RunPaths",
    "append_jsonl",
    "current_git_sha",
    "default_metrics",
    "default_verdict",
    "git_is_dirty",
    "git_remote_url",
    "make_run_id",
    "update_json",
    "utc_now",
    "write_placeholder_artifacts",
]
