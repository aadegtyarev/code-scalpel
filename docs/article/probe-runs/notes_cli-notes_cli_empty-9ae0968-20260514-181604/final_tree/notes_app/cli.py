import click
from .storage import NotesStorage

click.disable_unicode_literals = True

class NotesCLI:
    def __init__(self, storage):
        self.storage = storage

    @click.group()
    def cli():
        pass

    @cli.command()
    @click.argument('note', nargs=-1)
    def add(note):
        note_text = ' '.join(note)
        try:
            storage.add(note_text)
            click.echo(f'Note added: {note_text}')
        except ValueError as e:
            click.echo(e, err=True)

    @cli.command()
    def list():
        notes = storage.list()
        if not notes:
            click.echo('No notes found.')
        else:
            for i, note in enumerate(notes):
                click.echo(f'{i}: {note}')

    @cli.command()
    @click.argument('query')
    def search(query):
        results = storage.search(query)
        if not results:
            click.echo(f'No notes found for query: {query}')
        else:
            for i, note in enumerate(results):
                click.echo(f'{i}: {note}')

    @cli.command()
    @click.argument('index', type=int)
    def delete(index):
        try:
            storage.delete(index)
            click.echo(f'Note at index {index} deleted.')
        except (IndexError, ValueError) as e:
            click.echo(e, err=True)

if __name__ == '__main__':
    storage = NotesStorage()
    cli()