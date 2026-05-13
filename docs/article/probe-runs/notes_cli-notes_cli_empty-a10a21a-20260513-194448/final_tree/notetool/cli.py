# notetool/cli.py
import click
from .storage import JsonStorage

click.group()
def cli():
    pass

@cli.command()
@click.argument('note')
def add(note):
    storage = JsonStorage('notes.json')
    storage.add_note(note)
    click.echo(f"Note added: {note}")

@cli.command()
def list_notes():
    storage = JsonStorage('notes.json')
    notes = storage.get_notes()
    for i, note in enumerate(notes, 1):
        click.echo(f"{i}: {note}")