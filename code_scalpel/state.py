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


class AgentState(BaseModel):
    current_task: str | None = None
    step_phase: StepPhase = "idle"
    dirty_patch: bool = False
    mode: str = "ask"
    profile: str = "local"
    context_limit: int = 24000
    max_files: int = 3
    max_file_lines: int = 400
    last_test_status: Literal["passed", "failed", "unknown"] = "unknown"
    debug_attempts: int = 0
    completed_tasks: list[str] = Field(default_factory=list)
    last_saved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

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
