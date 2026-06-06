import typer
from notes_cli.storage import Storage
from notes_cli.models import Note

app = typer.Typer()


@app.command()
def add(
    title: str = typer.Option(..., "--title", "-t", help="Заметка заголовок"),
    content: str = typer.Option(..., "--content", "-c", help="Заметка текст"),
    db: str = typer.Option("notes.json", "--db", "-d", help="Путь к JSON-файлу"),
) -> None:
    """Добавить новую заметку."""
    storage = Storage(db)
    note = storage.add(Note(title=title, content=content))
    typer.echo(f"Заметка добавлена с ID {note.id}")


@app.command()
def list(
    db: str = typer.Option("notes.json", "--db", "-d", help="Путь к JSON-файлу"),
) -> None:
    """Вывести все заметки."""
    storage = Storage(db)
    notes = storage.load()
    if not notes:
        typer.echo("Нет заметок")
        return
    for note in notes:
        typer.echo(f"[{note.id}] {note.title} ({note.created_at})")
        typer.echo(f"    {note.content}")


@app.command()
def search(
    query: str = typer.Option(..., "--query", "-q", help="Текст для поиска"),
    db: str = typer.Option("notes.json", "--db", "-d", help="Путь к JSON-файлу"),
) -> None:
    """Поиск заметок по заголовку или тексту."""
    storage = Storage(db)
    notes = storage.search(query)
    if not notes:
        typer.echo("Ничего не найдено")
        return
    for note in notes:
        typer.echo(f"[{note.id}] {note.title} ({note.created_at})")
        typer.echo(f"    {note.content}")


@app.command()
def delete(
    id: int = typer.Option(..., "--id", "-i", help="ID заметки для удаления"),
    db: str = typer.Option("notes.json", "--db", "-d", help="Путь к JSON-файлу"),
) -> None:
    """Удалить заметку по ID."""
    storage = Storage(db)
    if storage.delete(id):
        typer.echo(f"Заметка {id} удалена")
    else:
        typer.echo(f"Заметка с ID {id} не найдена")


def main():
    app()


if __name__ == "__main__":
    main()
