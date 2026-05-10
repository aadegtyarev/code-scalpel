from __future__ import annotations

from pathlib import Path

import pytest

from code_scalpel.llm.adapter import ChatResponse
from code_scalpel.session import Session
from code_scalpel.state import AgentState

# --- AgentState ---


def test_default_state() -> None:
    s = AgentState()
    assert s.step_phase == "idle"
    assert s.dirty_patch is False
    assert s.completed_tasks == []


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    s = AgentState(current_task="T001", dirty_patch=True, step_phase="applying")
    s.save(tmp_path)
    loaded = AgentState.load(tmp_path)
    assert loaded.current_task == "T001"
    assert loaded.dirty_patch is True
    assert loaded.step_phase == "applying"


def test_save_is_atomic(tmp_path: Path) -> None:
    s = AgentState(current_task="T001")
    s.save(tmp_path)
    # tmp file must not remain after save
    assert not (tmp_path / ".code-scalpel" / "STATE.tmp").exists()
    assert (tmp_path / ".code-scalpel" / "STATE.json").exists()


def test_load_returns_default_when_no_file(tmp_path: Path) -> None:
    s = AgentState.load(tmp_path)
    assert s.step_phase == "idle"


def test_reset_creates_fresh_state(tmp_path: Path) -> None:
    old = AgentState(current_task="T999", dirty_patch=True)
    old.save(tmp_path)
    fresh = AgentState.reset(tmp_path)
    assert fresh.current_task is None
    assert fresh.dirty_patch is False
    reloaded = AgentState.load(tmp_path)
    assert reloaded.current_task is None


def test_save_updates_last_saved_at(tmp_path: Path) -> None:
    s = AgentState()
    before = s.last_saved_at
    s.save(tmp_path)
    loaded = AgentState.load(tmp_path)
    assert loaded.last_saved_at >= before


# --- Session ---


def test_session_record() -> None:
    sess = Session()
    resp = ChatResponse(content="hi", prompt_tokens=100, completion_tokens=50, cost=0.01)
    sess.record(resp)
    assert sess.total_prompt_tokens == 100
    assert sess.total_completion_tokens == 50
    assert sess.total_cost == pytest.approx(0.01)
    assert sess.requests == 1


def test_session_record_no_cost() -> None:
    sess = Session()
    resp = ChatResponse(content="hi", prompt_tokens=10, completion_tokens=5, cost=None)
    sess.record(resp)
    assert sess.total_cost == 0.0


def test_session_summary_line() -> None:
    sess = Session()
    sess.record(ChatResponse(content="x", prompt_tokens=5000, completion_tokens=2000, cost=0.005))
    line = sess.summary_line()
    assert "↑5k" in line
    assert "↓2k" in line
    assert "$0.0050" in line


def test_context_bar_normal() -> None:
    sess = Session()
    bar = sess.context_bar(5000, 24000, warn=0.70, critical=0.90)
    assert "5k/24k" in bar
    assert "red" not in bar
    assert "yellow" not in bar


def test_context_bar_warn() -> None:
    sess = Session()
    bar = sess.context_bar(17000, 24000, warn=0.70, critical=0.90)
    assert "yellow" in bar


def test_context_bar_critical() -> None:
    sess = Session()
    bar = sess.context_bar(22000, 24000, warn=0.70, critical=0.90)
    assert "red" in bar
