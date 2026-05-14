import json
from pathlib import Path
def setup_module(module):
    notes_path = Path('data/notes.json')
    with open(notes_path, 'w') as file:
        json.dump([], file)
def teardown_module(module):
    notes_path = Path('data/notes.json')
    with open(notes_path, 'w') as file:
        json.dump([], file)