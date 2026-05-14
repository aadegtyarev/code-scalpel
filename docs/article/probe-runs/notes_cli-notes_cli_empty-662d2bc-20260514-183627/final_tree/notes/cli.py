import click
from .storage import Storage
click.group()
def cli():
    pass

@cli.command()
@click.argument('note')
def add(note):
    storage = Storage()
    storage.add_note(note)
    click.echo(f'Note added: {note}')

@cli.command()
def list():
    storage = Storage()
    notes = storage.get_notes()
    for i, note in enumerate(notes, start=1):
        click.echo(f'{i}. {note}')

@cli.command()
@click.argument('query')
def search(query):
    storage = Storage()
    results = storage.search_notes(query)
    for result in results:
        click.echo(result)

@cli.command()
@click.argument('index', type=int)
def delete(index):
    storage = Storage()
    if storage.delete_note(index):
        click.echo(f'Note {index} deleted.')
    else:
        click.echo(f'Note {index} not found.')