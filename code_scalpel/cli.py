from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from code_scalpel.config import load_config

app = typer.Typer(name="code-scalpel", help="TUI coding agent for weak local LLMs.")

_PathArg = Annotated[
    Path,
    typer.Argument(
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
        help="Working directory (default: current dir)",
    ),
]


@app.command()
def tui(path: _PathArg = Path(".")) -> None:
    """Launch TUI."""
    _launch(path)


@app.command()
def ask(path: _PathArg = Path(".")) -> None:
    """Start interactive ask session."""
    _launch(path)


def _launch(path: Path) -> None:
    from code_scalpel.tui.app import ScalpelApp

    config = load_config()
    ScalpelApp(config=config, cwd=path).run()
