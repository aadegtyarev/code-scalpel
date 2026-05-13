"""Тесты TodoStore — добавление, листинг, done, remove."""

from __future__ import annotations

from pathlib import Path

import pytest

from mini_cli.core import TodoStore


@pytest.fixture
def store(tmp_path: Path) -> TodoStore:
    return TodoStore(tmp_path / "todos.json")


def test_add_assigns_sequential_ids(store: TodoStore) -> None:
    first = store.add("buy milk")
    second = store.add("walk dog")
    assert first.id == 1
    assert second.id == 2
    assert second.text == "walk dog"


def test_list_returns_what_was_added(store: TodoStore) -> None:
    store.add("a")
    store.add("b")
    items = store.list()
    assert [t.text for t in items] == ["a", "b"]
    assert all(not t.done for t in items)


def test_mark_done_flips_flag(store: TodoStore) -> None:
    item = store.add("read book")
    result = store.mark_done(item.id)
    assert result is not None
    assert result.done is True
    # Перечитать из файла — изменение должно сохраниться
    fresh = store.list()
    assert fresh[0].done is True


def test_mark_done_unknown_id_returns_none(store: TodoStore) -> None:
    assert store.mark_done(999) is None


def test_remove_drops_item(store: TodoStore) -> None:
    store.add("a")
    store.add("b")
    assert store.remove(1) is True
    items = store.list()
    assert [t.id for t in items] == [2]


def test_remove_unknown_id_returns_false(store: TodoStore) -> None:
    store.add("a")
    assert store.remove(42) is False
    assert len(store.list()) == 1


def test_empty_store_lists_empty(store: TodoStore) -> None:
    assert store.list() == []
