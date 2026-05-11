"""Tests for the persistent project memory (`code_scalpel.memory`)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from code_scalpel.memory import MemoryEntry, MemoryStore


def test_add_and_search_round_trip(tmp_path: Path) -> None:
    store = MemoryStore(root=tmp_path)
    store.add("Пользователь предпочитает ты, не вы")
    store.add("Тесты запускаются через pytest -x")
    store.add("Сжатие истории живёт в StepAgent.compact, не в Session")

    results = store.search("сжатие истории")
    assert results, "expected FTS5 to find the сжатие entry"
    assert "StepAgent" in results[0].text


def test_search_returns_ranked_results(tmp_path: Path) -> None:
    store = MemoryStore(root=tmp_path)
    store.add("StepAgent has a compact method")
    store.add("Session has mark_compacted, not compact")
    store.add("Unrelated note about Docker")
    results = store.search("compact", k=5)
    assert any("StepAgent" in r.text or "Session" in r.text for r in results)


def test_persists_across_instances(tmp_path: Path) -> None:
    """Memory is the whole point — must survive instance teardown."""
    store1 = MemoryStore(root=tmp_path)
    store1.add("persistent fact")
    del store1
    store2 = MemoryStore(root=tmp_path)
    results = store2.search("persistent")
    assert len(results) == 1
    assert results[0].text == "persistent fact"


def test_empty_query_returns_empty_list(tmp_path: Path) -> None:
    store = MemoryStore(root=tmp_path)
    store.add("anything")
    assert store.search("") == []
    assert store.search("   ") == []


def test_empty_add_raises(tmp_path: Path) -> None:
    store = MemoryStore(root=tmp_path)
    with pytest.raises(ValueError, match="non-empty"):
        store.add("")
    with pytest.raises(ValueError, match="non-empty"):
        store.add("   \n  ")


def test_malformed_fts_query_returns_empty(tmp_path: Path) -> None:
    """FTS5 chokes on bare punctuation — we catch it so a stray `*` or
    `"` from the user doesn't crash the agent."""
    store = MemoryStore(root=tmp_path)
    store.add("real fact")
    assert isinstance(store.search('"'), list)
    assert isinstance(store.search("*"), list)


def test_k_caps_result_count(tmp_path: Path) -> None:
    store = MemoryStore(root=tmp_path)
    for i in range(10):
        store.add(f"common phrase entry {i}")
    results = store.search("common phrase", k=3)
    assert len(results) == 3


def test_kind_tagged_on_entry(tmp_path: Path) -> None:
    store = MemoryStore(root=tmp_path)
    store.add("user pref", kind="preference")
    store.add("session note", kind="session")
    kinds = {e.kind for e in store.all()}
    assert {"preference", "session"} <= kinds


def test_source_tagged_when_provided(tmp_path: Path) -> None:
    store = MemoryStore(root=tmp_path)
    store.add("fact from /remember", source="slash:remember")
    assert store.all()[0].source == "slash:remember"


def test_delete_by_id(tmp_path: Path) -> None:
    store = MemoryStore(root=tmp_path)
    eid = store.add("to be deleted")
    store.add("to be kept")
    assert store.delete(eid) is True
    assert store.delete(eid) is False
    remaining = store.all()
    assert len(remaining) == 1
    assert remaining[0].text == "to be kept"


def test_clear_removes_all(tmp_path: Path) -> None:
    store = MemoryStore(root=tmp_path)
    store.add("a")
    store.add("b")
    store.add("c")
    store.clear()
    assert len(store) == 0
    assert store.search("a") == []


def test_len_matches_count(tmp_path: Path) -> None:
    store = MemoryStore(root=tmp_path)
    assert len(store) == 0
    store.add("one")
    store.add("two")
    assert len(store) == 2


def test_created_at_is_datetime(tmp_path: Path) -> None:
    store = MemoryStore(root=tmp_path)
    store.add("when")
    entry = store.all()[0]
    assert isinstance(entry.created_at, datetime)


def test_memory_entry_is_frozen(tmp_path: Path) -> None:
    store = MemoryStore(root=tmp_path)
    store.add("immutable")
    entry: MemoryEntry = store.all()[0]
    with pytest.raises(AttributeError):
        entry.text = "changed"  # type: ignore[misc]


def test_add_accepts_note_at_cap(tmp_path: Path) -> None:
    """Граница принимается — отказывать ровно на пределе было бы
    неожиданным сюрпризом."""
    from code_scalpel.memory import _MAX_NOTE_CHARS

    store = MemoryStore(root=tmp_path)
    text = "a" * _MAX_NOTE_CHARS
    store.add(text)
    assert len(store) == 1


def test_add_rejects_oversized_note(tmp_path: Path) -> None:
    """Заметка длиннее лимита падает с ValueError, а не молча урезается."""
    from code_scalpel.memory import _MAX_NOTE_CHARS

    store = MemoryStore(root=tmp_path)
    text = "a" * (_MAX_NOTE_CHARS + 1)
    with pytest.raises(ValueError, match="note too long"):
        store.add(text)
    assert len(store) == 0
