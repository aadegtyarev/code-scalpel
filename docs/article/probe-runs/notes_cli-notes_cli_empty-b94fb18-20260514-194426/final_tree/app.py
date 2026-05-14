import click
from storage import NoteStorage

storage = NoteStorage()

click.group()
def cli():
    pass

@cli.command()
@click.argument('note')
def add(note):
    """Добавить новую заметку."""
    storage.add_note(note)
    print(f"Added note: {note}")

@cli.command(name='list')
def list_notes():
    """Список всех заметок."""
    notes = storage.get_notes()
    for i, note in enumerate(notes):
        print(f"{i}: {note}")

@cli.command()
@click.argument('query')
def search(query):
    """Поиск заметки по запросу."""
    results = storage.search_notes(query)
    if results:
        for i, note in enumerate(results):
            print(f"{i}: {note}")
    else:
        print("No notes found.")

@cli.command()
@click.argument('note_id', type=int)
def delete(note_id):
    """Удалить заметку по ID."""
    storage.delete_note(note_id)
    print(f"Deleted note with ID: {note_id}")

if __name__ == '__main__':
    cli()