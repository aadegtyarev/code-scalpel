"""Full-view modal for the background-jobs registry (Ctrl+J).

The inline JobsBar shows kinds only — "⚙ 2 jobs: map · step". For a
session running supervised autonomous mode, multiple long-running
jobs stack up and the user wants to see who's been running for how
long and what each one is actually doing. This modal renders the
full snapshot: kind, description, elapsed time. Escape closes.

No cancel buttons here yet — Esc on the main screen still cancels
the active step worker; per-job cancel waits until JobRegistry
learns about cancellable jobs (RISK in the review backlog).
"""

from __future__ import annotations

from datetime import UTC, datetime

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from code_scalpel.jobs import JobRegistry


class JobsModal(ModalScreen[None]):
    """Modal that lists every live job with kind, description, age."""

    DEFAULT_CSS = """
    JobsModal {
        align: center middle;
    }
    JobsModal > Vertical {
        background: #161616;
        border: round #3a3a3a;
        width: 70%;
        height: auto;
        max-height: 80%;
        padding: 1 2;
    }
    JobsModal #jm-header {
        height: auto;
        color: #d0d0d0;
        text-style: bold;
        padding: 0 0 1 0;
    }
    JobsModal #jm-empty {
        height: auto;
        color: #888888;
    }
    JobsModal .jm-row {
        height: auto;
        color: #c0c0c0;
        padding: 0 0 0 0;
    }
    JobsModal #jm-hint {
        height: auto;
        color: #585858;
        padding: 1 0 0 0;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Close", show=False),
        Binding("ctrl+j", "dismiss", "Close", show=False),
    ]

    def __init__(self, registry: JobRegistry) -> None:
        super().__init__()
        self._registry = registry

    def compose(self) -> ComposeResult:
        snap = self._registry.snapshot()
        now = datetime.now(UTC)
        with Vertical():
            yield Static(f"Background jobs ({len(snap)})", id="jm-header")
            if not snap:
                yield Static("● idle — nothing running.", id="jm-empty")
            else:
                with VerticalScroll():
                    for job in snap:
                        age = (now - job.started_at).total_seconds()
                        age_str = _fmt_age(age)
                        # Markup intentionally on — `kind` and `description` are
                        # our own constants from track() call-sites, not user
                        # data; rich tags are safe here.
                        line = (
                            f"[bold #c0c0c0]{job.kind}[/]"
                            f"  [#888888]{age_str}[/]\n"
                            f"  [#a0a0a0]{job.description}[/]"
                        )
                        yield Static(line, classes="jm-row")
            yield Static("Esc or Ctrl+J to close.", id="jm-hint")


def _fmt_age(seconds: float) -> str:
    """Short human age: 3s / 42s / 1m12s / 5m / 1h03m. Designed to fit
    in the right margin of a row without wrapping."""
    if seconds < 60:
        return f"{int(seconds)}s"
    mins, secs = divmod(int(seconds), 60)
    if mins < 60:
        return f"{mins}m{secs:02d}s" if secs else f"{mins}m"
    hrs, mins = divmod(mins, 60)
    return f"{hrs}h{mins:02d}m"
