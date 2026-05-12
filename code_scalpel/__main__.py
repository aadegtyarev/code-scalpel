"""Module entry point.

Lets `python -m code_scalpel` work and gives PyInstaller a stable file
to target. The CLI itself lives in `code_scalpel.cli:app` (typer)."""

from code_scalpel.cli import app

if __name__ == "__main__":
    app()
