from notes import add, list_notes, search, delete

def test_add():
    note_id = add('Test note')
    assert isinstance(note_id, int)
    assert note_id > 0

def test_list():
    add('First note')
    add('Second note')
    notes = list_notes()
    assert len(notes) == 2
    assert notes[0]['text'] == 'First note'
    assert notes[1]['text'] == 'Second note'

def test_search():
    add('Test search')
    results = search('search')
    assert len(results) == 1
    assert results[0]['text'] == 'Test search'

def test_delete():
    note_id = add('Note to delete')
    assert delete(note_id)
    notes = list_notes()
    assert len(notes) == 0