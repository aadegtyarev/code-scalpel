import click
from notes.storage import add_note, list_notes, search_notes, delete_note

click.group()
def main():
    pass

@main.command()
@click.argument('note')
def add(note):
    add_note(note)
    print(f'Note added: {note}')

@main.command()
def list():
    notes = list_notes()
    for i, note in enumerate(notes, start=1):
        print(f'{i}. {note}')