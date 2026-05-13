from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

StepPhase = Literal["idle", "generating", "reviewing", "applying", "testing"]

_STATE_DIR = Path(".code-scalpel")
_STATE_FILE = _STATE_DIR / "STATE.json"
_STATE_TMP = _STATE_DIR / "STATE.tmp"


class PersistedFork(BaseModel):
    """JSON-сериализуемый снимок одной pending-fork записи.

    Полный `PendingFork` из upstream_queue.py не сериализуется
    напрямую (frozen dataclass, ForkOption-кортежи). Здесь —
    плоская версия, в которую mapping строится на сохранении и
    разбирается на restore'е. Хранятся только данные нужные чтобы
    переоткрыть очередь и показать пользователю «N pending forks»:
    fork_id и question — для идентификации, picker-chosen — чтобы
    знать какой ответ builder уже использует.
    """

    fork_id: str
    question: str
    picker_chosen: str


class AgentState(BaseModel):
    current_task: str | None = None
    step_phase: StepPhase = "idle"
    dirty_patch: bool = False
    mode: str = "ask"
    profile: str = "local"
    context_limit: int = 16384
    max_files: int = 3
    max_file_lines: int = 400
    last_test_status: Literal["passed", "failed", "unknown"] = "unknown"
    debug_attempts: int = 0
    completed_tasks: list[str] = Field(default_factory=list)
    last_saved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    # v0.12.5 full-resume поля
    # ─────────────────────────
    # Хеш _history (после последней auto-compact'ации) — нужен
    # чтобы при resume отличить «то же состояние что мы сохранили»
    # от «пользователь руками поправил историю / агент рестартовал
    # с чистого листа». None = резюмировать нечего (свежая сессия).
    history_summary_hash: str | None = None
    # Снимок очереди upstream-форков. На v0.12 builder продолжал
    # работу на picker'овском временном ответе; если процесс
    # упал — нам надо при restore показать пользователю «N forks
    # ждут upstream, /escalate или конец /go их флашит».
    open_fork_questions: list[PersistedFork] = Field(default_factory=list)

    def save(self, root: Path = Path(".")) -> None:
        state_dir = root / _STATE_DIR
        state_dir.mkdir(exist_ok=True)
        tmp = root / _STATE_TMP
        target = root / _STATE_FILE
        updated = self.model_copy(update={"last_saved_at": datetime.now(UTC)})
        tmp.write_text(updated.model_dump_json(indent=2))
        os.replace(tmp, target)  # atomic on POSIX

    @classmethod
    def load(cls, root: Path = Path(".")) -> AgentState:
        path = root / _STATE_FILE
        if not path.exists():
            return cls()
        return cls.model_validate_json(path.read_text())

    @classmethod
    def reset(cls, root: Path = Path(".")) -> AgentState:
        state = cls()
        state.save(root)
        return state
