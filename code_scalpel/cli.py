from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from code_scalpel import __version__
from code_scalpel.config import load_config

app = typer.Typer(name="code-scalpel", help="TUI coding agent for weak local LLMs.")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"code-scalpel {__version__}")
        raise typer.Exit()


@app.command()
def main(
    path: Annotated[
        Path | None,
        typer.Argument(
            exists=True,
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
            help="Working directory (default: current dir)",
            show_default=False,
            hidden=True,
        ),
    ] = None,
    path_opt: Annotated[
        Path | None,
        typer.Option(
            "--path",
            exists=True,
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
            help="Working directory (default: current dir)",
            show_default=False,
        ),
    ] = None,
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show version and exit.",
        ),
    ] = False,
) -> None:
    """Launch the TUI in the given directory (defaults to current)."""
    from code_scalpel.tui.app import ScalpelApp

    cwd = (path_opt or path or Path(".")).resolve()
    config = load_config()
    scalpel = ScalpelApp(config=config, cwd=cwd)
    scalpel.run()
    summary = getattr(scalpel, "_exit_summary", None)
    if summary:
        typer.echo(summary)
