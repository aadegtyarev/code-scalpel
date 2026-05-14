import pytest
from click.testing import CliRunner
from app import cli

runner = CliRunner()

def test_add():
    result = runner.invoke(cli, ['add', 'Test note'])
    assert result.exit_code == 0
    assert "Added note: Test note" in result.output

def test_list_notes():
    result = runner.invoke(cli, ['list'])
    assert result.exit_code == 0
    assert "Listing all notes..." in result.output

def test_search_notes():
    result = runner.invoke(cli, ['search', 'Test'])
    assert result.exit_code == 0
    assert "Searching for notes with query: Test" in result.output

def test_delete_note():
    result = runner.invoke(cli, ['delete', '0'])
    assert result.exit_code == 0
    assert "Deleted note with ID: 0" in result.output