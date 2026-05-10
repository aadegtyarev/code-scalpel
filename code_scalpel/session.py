from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from code_scalpel.llm.adapter import ChatResponse


@dataclass
class Session:
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_cost: float = 0.0
    requests: int = 0
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def record(self, response: ChatResponse) -> None:
        self.total_prompt_tokens += response.prompt_tokens
        self.total_completion_tokens += response.completion_tokens
        if response.cost is not None:
            self.total_cost += response.cost
        self.requests += 1

    @property
    def elapsed_seconds(self) -> float:
        return (datetime.now(UTC) - self.started_at).total_seconds()

    def context_bar(self, used: int, limit: int, warn: float, critical: float) -> str:
        """Return footer string: '5k/24k · 68%'  colored by threshold."""
        pct = used / limit if limit else 0.0
        label = f"{used // 1000}k/{limit // 1000}k · {pct:.0%}"
        if pct >= critical:
            return f"[red]{label}[/red]"
        if pct >= warn:
            return f"[yellow]{label}[/yellow]"
        return label

    def summary_line(self) -> str:
        """One-line stats for footer: tokens · cost · elapsed."""
        mins, secs = divmod(int(self.elapsed_seconds), 60)
        elapsed = f"{mins}m {secs}s" if mins else f"{secs}s"
        cost = f" · ${self.total_cost:.4f}" if self.total_cost else ""
        total = self.total_prompt_tokens + self.total_completion_tokens
        return f"↑{self.total_prompt_tokens // 1000}k ↓{self.total_completion_tokens // 1000}k ({total // 1000}k total){cost} · {elapsed}"
