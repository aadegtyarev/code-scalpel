from __future__ import annotations

from textual.widgets import RichLog


class OutputLog(RichLog):
    """Infinite scrollable output stream. Cards mount here inline."""

    DEFAULT_CSS = """
    OutputLog {
        width: 1fr;
        height: 1fr;
        background: $bg;
        border: none;
        scrollbar-color: $fg-muted;
        scrollbar-background: $bg;
        padding: 0 1;
    }
    """

    def __init__(self) -> None:
        super().__init__(highlight=True, markup=True, wrap=True, id="output")

    def print_user(self, text: str) -> None:
        self.write(f"[bold]{text}[/bold]")

    def print_assistant(self, text: str) -> None:
        self.write(text)

    def print_status(self, text: str) -> None:
        self.write(f"[dim]{text}[/dim]")

    def print_error(self, text: str) -> None:
        self.write(f"[red]{text}[/red]")
