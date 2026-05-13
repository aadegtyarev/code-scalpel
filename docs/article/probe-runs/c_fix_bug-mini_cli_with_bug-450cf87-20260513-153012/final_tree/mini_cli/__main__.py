"""CLI-обёртка — typer-команды поверх TodoStore."""

from __future__ import annotations

from pathlib import Path

import typer

from mini_cli.core import TodoStore

app = typer.Typer(no_args_is_help=True, add_completion=False)

DEFAULT_STORE = Path.home() / ".mini-cli" / "todos.json"


def _store() -> TodoStore:
    return TodoStore(DEFAULT_STORE)


@app.command()
def add(text: str) -> None:
    """Добавить пункт в список."""
    item = _store().add(text)
    typer.echo(f"added #{item.id}: {item.text}")


@app.command(name="list")
def list_cmd() -> None:
    """Показать все пункты."""
    items = _store().list()
    if not items:
        typer.echo("(пусто)")
        return
    for item in items:
        check = "x" if item.done else " "
        typer.echo(f"[{check}] #{item.id} {item.text}")


@app.command()
def done(todo_id: int) -> None:
    """Отметить пункт выполненным."""
    item = _store().mark_done(todo_id)
    if item is None:
        typer.echo(f"#{todo_id} not found", err=True)
        raise typer.Exit(1)
    typer.echo(f"done #{item.id}")


@app.command()
def remove(todo_id: int) -> None:
    """Удалить пункт по id."""
    if _store().remove(todo_id):
        typer.echo(f"removed #{todo_id}")
    else:
        typer.echo(f"#{todo_id} not found", err=True)
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
