from __future__ import annotations

from pathlib import Path

import typer

from code_scalpel.config import load_config

app = typer.Typer(name="code-scalpel", help="TUI coding agent for weak local LLMs.")


@app.command()
def ask(ctx: typer.Context) -> None:  # noqa: ARG001
    """Start interactive ask session."""
    _launch()


@app.command()
def tui() -> None:
    """Launch TUI (default)."""
    _launch()


def _launch() -> None:
    from code_scalpel.tui.app import ScalpelApp

    config = load_config()
    ScalpelApp(config=config, cwd=Path(".")).run()
