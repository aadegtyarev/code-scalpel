import pytest
import os
from notes import add_note, list_notes, search_notes, delete_note, load_notes

def setup_module():
    if os.path.exists('notes.json'):
        os.remove('notes.json')

def test_add_note():
    add_note("Test note")
    notes = load_notes()
    assert len(notes) == 1
    assert notes[0] == "Test note"

def test_list_notes():
    setup_module()  # Ensure a clean state before each test
    add_note("First note")
    add_note("Second note")
    captured_output = capture_stdout(list_notes)
    assert captured_output.strip().split('\n') == ["First note", "Second note"]

def test_search_notes():
    setup_module()  # Ensure a clean state before each test
    add_note("Test note with keyword")
    add_note("Another note")
    captured_output = capture_stdout(search_notes, "keyword")
    assert captured_output.strip() == "Test note with keyword"

def test_delete_note():
    setup_module()  # Ensure a clean state before each test
    add_note("Note to delete")
    notes_before = load_notes()
    delete_note(0)
    notes_after = load_notes()
    assert len(notes_after) == len(notes_before) - 1
    assert "Note to delete" not in notes_after

def test_integration():
    setup_module()  # Ensure a clean state before each test
    add_note("First note")
    add_note("Second note")
    captured_output_list = capture_stdout(list_notes)
    assert captured_output_list.strip().split('\n') == ["First note", "Second note"]
    
    captured_output_search = capture_stdout(search_notes, "First")
    assert captured_output_search.strip() == "First note"
    
    delete_note(0)
    captured_output_list_after_delete = capture_stdout(list_notes)
    assert captured_output_list_after_delete.strip().split('\n') == ["Second note"]
    
    add_note("Third note")
    captured_output_list_after_add = capture_stdout(list_notes)
    assert captured_output_list_after_add.strip().split('\n') == ["Second note", "Third note"]


def capture_stdout(func, *args):
    import io
    from contextlib import redirect_stdout
    f = io.StringIO()
    with redirect_stdout(f):
        func(*args)
    return f.getvalue()