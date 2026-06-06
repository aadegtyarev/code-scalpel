"""CLI-интерфейс для notes-cli."""

import sys

import click

from notes_cli.storage import NoteStorage


def _get_storage() -> NoteStorage:
    """Создать хранилище из аргумента CLI или по умолчанию."""
    ctx = click.get_current_context()
    path = ctx.params.get("data")
    if path:
        return NoteStorage(path=path)
    return NoteStorage()


@click.group()
@click.option("--data", default="notes.json", help="Путь к файлу данных.")
@click.pass_context
def cli(ctx: click.Context, data: str) -> None:
    """notes-cli — утилита для управления заметками."""
    ctx.ensure_object(dict)
    ctx.obj["data"] = data


@cli.command()
@click.argument("text")
@click.pass_context
def add(ctx: click.Context, text: str) -> None:
    """Создать новую заметку."""
    storage = _get_storage()
    note_id = storage.add(text)
    click.echo(f"Заметка #{note_id} сохранена.")


@cli.command("list")
@click.pass_context
def list_notes(ctx: click.Context) -> None:
    """Вывести все заметки."""
    storage = _get_storage()
    notes = storage.list_all()
    if not notes:
        click.echo("Заметок нет.")
        return
    for note in notes:
        click.echo(f"#{note['id']}: {note['text']}")


@cli.command()
@click.argument("query")
@click.pass_context
def search(ctx: click.Context, query: str) -> None:
    """Найти заметки по ключевым словам."""
    storage = _get_storage()
    results = storage.search(query)
    if not results:
        click.echo(f"Ничего не найдено по запросу: {query}")
        return
    for note in results:
        click.echo(f"#{note['id']}: {note['text']}")


@cli.command()
@click.argument("note_id", type=int)
@click.pass_context
def delete(ctx: click.Context, note_id: int) -> None:
    """Удалить заметку по ID."""
    storage = _get_storage()
    if storage.delete(note_id):
        click.echo(f"Заметка #{note_id} удалена.")
    else:
        click.echo(f"Заметка #{note_id} не найдена.", err=True)
        sys.exit(1)


def main(argv=None) -> None:
    """Точка входа CLI."""
    cli(argv=argv)


if __name__ == "__main__":
    main()
