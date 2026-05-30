import pytest
from notes.storage import NoteStorage
def run_main(args):
    from notes.cli import main
    import sys
    import io

    # Redirect stdout to capture the output
    old_stdout = sys.stdout
    new_stdout = io.StringIO()
    sys.stdout = new_stdout

    try:
        main(['notes'] + args)
    finally:
        # Reset stdout and get the captured output
        sys.stdout = old_stdout
        return new_stdout.getvalue()
def test_add_note(capsys):
    storage = NoteStorage()
    note_text = 'Test note'
    output = run_main(['add', note_text])
    assert f'Заметка добавлена: {note_text}' in output
def test_list_notes(capsys):
    storage = NoteStorage()
    storage.add_note('Test note 1')
    storage.add_note('Test note 2')
    output = run_main(['list'])
    assert 'Test note 1' in output
    assert 'Test note 2' in output
def test_search_notes(capsys):
    storage = NoteStorage()
    storage.add_note('Test search')
    output = run_main(['search', 'search'])
    assert 'Test search' in output
def test_delete_note(capsys):
    storage = NoteStorage()
    storage.add_note('Delete me')
    notes = storage.list_notes()
    note_id = notes[0]['id']
    output = run_main(['delete', str(note_id)])
    assert f'Заметка с ID {note_id} удалена.' in output