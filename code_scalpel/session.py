from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from code_scalpel.llm.adapter import ChatResponse


def _detect_language(text: str) -> str:
    """Heuristic: any Cyrillic = Russian; otherwise English. Sufficient for
    the local-coder use case where the user picks one and sticks with it."""
    for ch in text:
        if "Ѐ" <= ch <= "ӿ":
            return "Russian"
    return "English"


@dataclass
class Session:
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_cost: float = 0.0
    requests: int = 0
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    user_language: str | None = None  # auto-detected from first user message
    # Token counts at the most recent /compact. The footer subtracts these
    # from totals so the bar reflects "current context", not lifetime usage.
    # totals themselves stay intact for the exit cost summary.
    compact_baseline_prompt: int = 0
    compact_baseline_completion: int = 0

    def record(self, response: ChatResponse) -> None:
        self.total_prompt_tokens += response.prompt_tokens
        self.total_completion_tokens += response.completion_tokens
        if response.cost is not None:
            self.total_cost += response.cost
        self.requests += 1

    def mark_compacted(self) -> None:
        """Anchor the footer budget to the post-compact state. Cumulative
        totals are preserved — only the visible 'current context' drops."""
        self.compact_baseline_prompt = self.total_prompt_tokens
        self.compact_baseline_completion = self.total_completion_tokens

    @property
    def context_used_tokens(self) -> int:
        """Tokens spent on prompts+completions since the last /compact."""
        return (
            self.total_prompt_tokens
            - self.compact_baseline_prompt
            + self.total_completion_tokens
            - self.compact_baseline_completion
        )

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

    def detect_and_pin_language(self, text: str) -> str:
        """Set user_language from the given text if not already set; return it."""
        if self.user_language is None:
            self.user_language = _detect_language(text)
        return self.user_language

    def summary_line(self) -> str:
        """One-line stats for footer: tokens · cost · elapsed."""
        mins, secs = divmod(int(self.elapsed_seconds), 60)
        elapsed = f"{mins}m {secs}s" if mins else f"{secs}s"
        cost = f" · ${self.total_cost:.4f}" if self.total_cost else ""
        total = self.total_prompt_tokens + self.total_completion_tokens
        return f"↑{self.total_prompt_tokens // 1000}k ↓{self.total_completion_tokens // 1000}k ({total // 1000}k total){cost} · {elapsed}"

    def stats_report(
        self,
        *,
        ctx_limit: int | None = None,
        model: str | None = None,
        mode: str | None = None,
    ) -> str:
        """Multi-line human-readable session report for the /stats slash.

        Avoids any lookup the Session can't answer locally — caller passes
        the bits that live in app config (current mode, model name, ctx
        ceiling). Everything else comes from the accumulated ChatResponses.
        """
        secs = int(self.elapsed_seconds)
        mins, sec_rem = divmod(secs, 60)
        hrs, mins = divmod(mins, 60)
        if hrs:
            elapsed = f"{hrs}h {mins}m {sec_rem}s"
        elif mins:
            elapsed = f"{mins}m {sec_rem}s"
        else:
            elapsed = f"{sec_rem}s"

        total = self.total_prompt_tokens + self.total_completion_tokens
        avg_tps = self.total_completion_tokens / secs if secs > 0 else 0.0
        ctx_used = self.context_used_tokens

        rows: list[tuple[str, str]] = []
        if model is not None:
            rows.append(("model", model))
        if mode is not None:
            rows.append(("mode", mode))
        if self.user_language is not None:
            rows.append(("language", self.user_language))
        rows.append(("requests", str(self.requests)))
        rows.append(("elapsed", elapsed))
        rows.append(
            (
                "tokens",
                f"↑{self.total_prompt_tokens} prompt · "
                f"↓{self.total_completion_tokens} completion · {total} total",
            )
        )
        if avg_tps > 0:
            rows.append(("avg rate", f"{avg_tps:.1f} tok/s"))
        if ctx_limit:
            pct = ctx_used / ctx_limit * 100
            rows.append(("context", f"{ctx_used} / {ctx_limit} tokens ({pct:.0f}%)"))
        else:
            rows.append(("context", f"{ctx_used} tokens (no limit known)"))
        if self.compact_baseline_prompt or self.compact_baseline_completion:
            baseline = self.compact_baseline_prompt + self.compact_baseline_completion
            rows.append(("compacted at", f"{baseline} tokens"))
        if self.total_cost:
            rows.append(("cost", f"${self.total_cost:.4f}"))

        width = max(len(k) for k, _ in rows)
        return "\n".join(f"  {k.ljust(width)}  {v}" for k, v in rows)
