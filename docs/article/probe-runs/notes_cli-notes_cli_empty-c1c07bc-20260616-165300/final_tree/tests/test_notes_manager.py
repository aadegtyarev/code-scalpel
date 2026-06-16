"""Тесты для модуля notes_manager."""

import json
from datetime import datetime

from notes_manager import (
    add_note,
    delete_note,
    list_notes,
    load_notes,
    save_notes,
    search_notes,
)


def test_load_notes_file_not_found(tmp_path):
    """load_notes возвращает [] если файл не существует."""
    path = tmp_path / "no_notes.json"
    assert load_notes(str(path)) == []


def test_load_notes_empty_file(tmp_path):
    """load_notes возвращает [] для пустого JSON-массива."""
    path = tmp_path / "notes.json"
    path.write_text("[]", encoding="utf-8")
    assert load_notes(str(path)) == []


def test_load_notes_with_data(tmp_path):
    """load_notes возвращает данные из существующего файла."""
    path = tmp_path / "notes.json"
    data = [{"id": 1, "text": "test", "timestamp": "2026-01-01T00:00:00"}]
    path.write_text(json.dumps(data), encoding="utf-8")
    assert load_notes(str(path)) == data


def test_save_notes(tmp_path):
    """save_notes записывает данные в JSON-файл."""
    path = tmp_path / "notes.json"
    data = [{"id": 1, "text": "test", "timestamp": "2026-01-01T00:00:00"}]
    save_notes(data, str(path))
    assert path.read_text(encoding="utf-8") == json.dumps(
        data, ensure_ascii=False, indent=2
    )


def test_add_note_returns_note_with_fields(tmp_path):
    """add_note возвращает заметку с полями id, text, timestamp."""
    path = tmp_path / "notes.json"
    note = add_note("Купить молоко", str(path))

    assert isinstance(note["id"], int)
    assert note["id"] == 1
    assert note["text"] == "Купить молоко"
    assert "timestamp" in note
    # проверяем, что timestamp — валидная ISO-строка
    datetime.fromisoformat(note["timestamp"])


def test_add_note_persists_to_file(tmp_path):
    """add_note сохраняет заметку в JSON-файл."""
    path = tmp_path / "notes.json"
    add_note("Первая", str(path))
    add_note("Вторая", str(path))

    notes = json.loads(path.read_text(encoding="utf-8"))
    assert len(notes) == 2
    assert notes[0]["text"] == "Первая"
    assert notes[1]["text"] == "Вторая"
    assert notes[0]["id"] == 1
    assert notes[1]["id"] == 2


def test_list_notes_empty(tmp_path):
    """list_notes возвращает [] если заметок нет."""
    path = tmp_path / "notes.json"
    assert list_notes(str(path)) == []


def test_list_notes_with_data(tmp_path):
    """list_notes возвращает список добавленных заметок."""
    path = tmp_path / "notes.json"
    add_note("A", str(path))
    add_note("B", str(path))

    notes = list_notes(str(path))
    assert len(notes) == 2


def test_search_notes_case_insensitive(tmp_path):
    """search_notes ищет регистронезависимо."""
    path = tmp_path / "notes.json"
    add_note("Купить молоко", str(path))
    add_note("Купить хлеб", str(path))
    add_note("Позвонить маме", str(path))

    result = search_notes("Купить", str(path))
    assert len(result) == 2

    result = search_notes("купить", str(path))
    assert len(result) == 2


def test_search_notes_partial_match(tmp_path):
    """search_notes находит частичное совпадение."""
    path = tmp_path / "notes.json"
    add_note("Купить молоко", str(path))

    result = search_notes("молок", str(path))
    assert len(result) == 1


def test_search_notes_no_match(tmp_path):
    """search_notes возвращает [] если ничего не найдено."""
    path = tmp_path / "notes.json"
    add_note("Купить молоко", str(path))

    result = search_notes("пиво", str(path))
    assert result == []


def test_search_notes_empty_storage(tmp_path):
    """search_notes возвращает [] если файла вообще нет."""
    path = tmp_path / "notes.json"
    assert search_notes("test", str(path)) == []


def test_delete_note_existing(tmp_path):
    """delete_note возвращает True и удаляет заметку."""
    path = tmp_path / "notes.json"
    add_note("Купить молоко", str(path))
    add_note("Купить хлеб", str(path))

    assert delete_note(1, str(path)) is True
    notes = list_notes(str(path))
    assert len(notes) == 1
    assert notes[0]["id"] == 2


def test_delete_note_not_found(tmp_path):
    """delete_note возвращает False для несуществующего ID."""
    path = tmp_path / "notes.json"
    add_note("Купить молоко", str(path))

    assert delete_note(999, str(path)) is False
    assert len(list_notes(str(path))) == 1


def test_delete_note_empty_storage(tmp_path):
    """delete_note возвращает False если в хранилище пусто."""
    path = tmp_path / "notes.json"
    assert delete_note(1, str(path)) is False
