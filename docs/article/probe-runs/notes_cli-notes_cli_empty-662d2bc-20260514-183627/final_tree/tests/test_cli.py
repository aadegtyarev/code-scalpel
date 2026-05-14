import pytest
from click.testing import CliRunner
from notes.cli import cli
from notes.storage import Storage

def test_add_note():
    runner = CliRunner()
    result = runner.invoke(cli, ['add', 'Test note'])
    assert result.exit_code == 0
    storage = Storage()
    notes = storage.get_notes()
    assert len(notes) == 1
    assert notes[0] == 'Test note'

def test_list_notes():
    runner = CliRunner()
    runner.invoke(cli, ['add', 'First note'])
    runner.invoke(cli, ['add', 'Second note'])
    result = runner.invoke(cli, ['list'])
    assert result.exit_code == 0
    assert '1. First note' in result.output
    assert '2. Second note' in result.output

def test_search_notes():
    runner = CliRunner()
    runner.invoke(cli, ['add', 'Note with keyword'])
    runner.invoke(cli, ['add', 'Another note'])
    result = runner.invoke(cli, ['search', 'keyword'])
    assert result.exit_code == 0
    assert 'Note with keyword' in result.output
    assert 'Another note' not in result.output

def test_delete_note():
    runner = CliRunner()
    runner.invoke(cli, ['add', 'First note'])
    runner.invoke(cli, ['add', 'Second note'])
    result = runner.invoke(cli, ['delete', 1])
    assert result.exit_code == 0
    storage = Storage()
    notes = storage.get_notes()
    assert len(notes) == 1
    assert notes[0] == 'Second note'