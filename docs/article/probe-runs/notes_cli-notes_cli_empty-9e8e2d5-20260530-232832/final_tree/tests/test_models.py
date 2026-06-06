from notes_cli.models import Note


def test_note_round_trip():
    note = Note.create("abc123", "Title", "Body")

    assert note.id == "abc123"
    assert note.title == "Title"
    assert note.body == "Body"
    assert note.created_at.endswith("Z")
    assert Note.from_dict(note.to_dict()) == note
