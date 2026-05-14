import click
import json
import os

click.group()
def cli():
    pass

@cli.command()
@click.argument('note')
def add(note):
    notes_path = 'notes.json'
    if not os.path.exists(notes_path):
        with open(notes_path, 'w') as f:
            json.dump([], f)
    with open(notes_path, 'r+') as f:
        notes = json.load(f)
        notes.append(note)
        f.seek(0)
        json.dump(notes, f, indent=4)