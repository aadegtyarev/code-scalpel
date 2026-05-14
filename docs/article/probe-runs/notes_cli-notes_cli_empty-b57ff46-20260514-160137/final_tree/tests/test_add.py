import pytest
from notes.cli import cli
def test_add(capsys):
    result = cli(['add', 'Test note'])
    captured = capsys.readouterr()
    assert captured.out == 'Note added: Test note\n'
    with open('notes.json', 'r') as f:
        notes = [json.loads(line) for line in f]
        assert len(notes) == 1
        assert notes[0]['note'] == 'Test note'