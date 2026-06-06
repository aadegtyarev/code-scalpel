"""Тесты для модуля storage."""

import json
from notes_cli.storage import (
    add_note,
    delete_note,
    get_next_id,
    load_notes,
    save_notes,
    search_notes,
)


def _write_tmp_file(tmp_path, filename, data):
    """Записать JSON-данные во временный файл."""
    filepath = tmp_path / filename
    filepath.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(filepath)


def test_load_notes_empty_file(tmp_path):
    """load_notes возвращает пустой список, если файл не существует."""
    path = str(tmp_path / "nonexistent.json")
    assert load_notes(path) == []


def test_load_notes_existing_file(tmp_path):
    """load_notes возвращает данные из файла."""
    data = [
        {"id": 1, "title": "test", "text": "hello", "created_at": "2024-01-01T00:00:00+00:00"},
    ]
    path = _write_tmp_file(tmp_path, "notes.json", data)
    assert load_notes(path) == data


def test_save_notes(tmp_path):
    """save_notes записывает данные в файл."""
    notes = [
        {"id": 1, "title": "t1", "text": "x", "created_at": "2024-01-01T00:00:00+00:00"},
    ]
    path = str(tmp_path / "notes.json")
    save_notes(notes, path)
    loaded = load_notes(path)
    assert loaded == notes


def test_add_note(tmp_path):
    """add_note создаёт заметку и сохраняет её."""
    path = str(tmp_path / "notes.json")
    note = add_note("hello world", "greeting", path)
    assert note["id"] == 1
    assert note["text"] == "hello world"
    assert note["title"] == "greeting"
    assert "created_at" in note

    loaded = load_notes(path)
    assert len(loaded) == 1
    assert loaded[0]["id"] == 1


def test_add_note_second_id(tmp_path):
    """Вторая заметка получает id=2."""
    path = str(tmp_path / "notes.json")
    add_note("first", "t1", path)
    note2 = add_note("second", "t2", path)
    assert note2["id"] == 2


def test_delete_note_found(tmp_path):
    """delete_note удаляет заметку и возвращает True."""
    path = str(tmp_path / "notes.json")
    add_note("keep", "k", path)
    add_note("remove", "r", path)
    assert delete_note(1, path) is True
    assert len(load_notes(path)) == 1
    assert load_notes(path)[0]["id"] == 2


def test_delete_note_not_found(tmp_path):
    """delete_note возвращает False, если заметка не найдена."""
    path = str(tmp_path / "notes.json")
    add_note("only", "o", path)
    assert delete_note(99, path) is False
    assert len(load_notes(path)) == 1


def test_search_notes_in_title(tmp_path):
    """search_notes находит по заголовку."""
    path = str(tmp_path / "notes.json")
    add_note("text1", "python", path)
    add_note("text2", "javascript", path)
    results = search_notes("python", path)
    assert len(results) == 1
    assert results[0]["title"] == "python"


def test_search_notes_in_text(tmp_path):
    """search_notes находит по тексту."""
    path = str(tmp_path / "notes.json")
    add_note("hello python", "t1", path)
    add_note("no match", "t2", path)
    results = search_notes("python", path)
    assert len(results) == 1
    assert results[0]["text"] == "hello python"


def test_search_notes_case_insensitive(tmp_path):
    """search_notes ищет без учёта регистра."""
    path = str(tmp_path / "notes.json")
    add_note("HELLO", "t1", path)
    results = search_notes("hello", path)
    assert len(results) == 1


def test_search_notes_no_match(tmp_path):
    """search_notes возвращает пустой список при отсутствии совпадений."""
    path = str(tmp_path / "notes.json")
    add_note("hello", "t1", path)
    results = search_notes("xyz", path)
    assert results == []


def test_get_next_id_empty():
    """get_next_id возвращает 1 для пустого списка."""
    assert get_next_id([]) == 1


def test_get_next_id_with_notes():
    """get_next_id возвращает max_id + 1."""
    notes = [
        {"id": 3, "title": "a", "text": "b", "created_at": "2024-01-01T00:00:00+00:00"},
        {"id": 1, "title": "c", "text": "d", "created_at": "2024-01-01T00:00:00+00:00"},
    ]
    assert get_next_id(notes) == 4
