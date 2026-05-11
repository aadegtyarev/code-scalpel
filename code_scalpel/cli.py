from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from code_scalpel.config import load_config

app = typer.Typer(name="code-scalpel", help="TUI coding agent for weak local LLMs.")


@app.command()
def main(
    path: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
            help="Working directory (default: current dir)",
        ),
    ] = Path("."),
) -> None:
    """Launch the TUI in the given directory (defaults to current)."""
    from code_scalpel.tui.app import ScalpelApp

    config = load_config()
    scalpel = ScalpelApp(config=config, cwd=path)
    scalpel.run()
    summary = getattr(scalpel, "_exit_summary", None)
    if summary:
        typer.echo(summary)
