import click
from notes.storage import load_notes, save_notes
click.disable_unicode_literals = True

def add_note(note):
    notes = load_notes()
    notes.append({'note': note})
    save_notes(notes)
    print(f'Note added: {note}')

@click.group()
def cli():
    pass

@cli.command()
@click.argument('note')
def add(note):
    add_note(note)

if __name__ == '__main__':
    cli()