import os
import json
from notes_cli.cli import cli

def test_add_note():
    result = cli.invoke(cli.commands['add'], ['Test note'])
    assert result.exit_code == 0
    with open('notes.json', 'r') as f:
        notes = json.load(f)
    assert notes == ['Test note']