"""Per-turn context-budget breakdown for the `/context` slash command.

The footer only carries the headline number ("4k/16k 26%"); when the
user wants to know *what* is eating their budget, the breakdown lives
here. Estimates use the ~4 char/token heuristic that the rest of
Session already trusts — not perfect, but consistent with the cost
accounting the user already sees in /stats.

Six categories track Claude Code's `/context` shape, mapped to our
moving parts:

  System prompt  — _SYSTEM_PROMPT (+ plan-mode addendum when active)
  Tools schema   — TOOL_SCHEMAS sent with every chat() request
  Overview       — build_map_overview, sent on every turn as the
                   "Project overview" block of the user message
  Memory recall  — last `Recalled notes` block surfaced by
                   StepAgent._recall_notes (empty until /remember
                   gets used)
  Conversation   — accumulated history rows (user + assistant)
  Free space     — limit minus the sum above; only meaningful when
                   the model's context_limit is known

The class is framework-agnostic — no Textual import. TUI builds the
report on /context, passes it to a ToolUseCard.
"""

from __future__ import annotations

from dataclasses import dataclass

_CHARS_PER_TOKEN = 4  # same heuristic Session uses for cost accounting


def _tokens(text: str) -> int:
    return max(0, len(text) // _CHARS_PER_TOKEN)


@dataclass(frozen=True)
class ContextSegment:
    """One row in the breakdown — name, token estimate, percent of the
    model's context limit. Percent is None when no limit is known
    (autodetect hadn't finished or LM Studio didn't say); the report
    still renders, just without the percent column."""

    name: str
    tokens: int
    percent: float | None

    def render(self, *, label_width: int) -> str:
        label = self.name.ljust(label_width)
        if self.percent is None:
            return f"  {label}  {self.tokens:>6} tokens"
        return f"  {label}  {self.tokens:>6} tokens ({self.percent:.1f}%)"


@dataclass(frozen=True)
class ContextReport:
    model: str
    ctx_limit: int  # 0 when unknown
    used_tokens: int
    segments: tuple[ContextSegment, ...]

    def render(self) -> str:
        """Plain-text block ready for a ToolUseCard. Designed to fit
        the card's inline render — no fancy boxes, no UTF-8 art beyond
        a simple progress bar so it survives any terminal."""
        lines: list[str] = []
        lines.append(f"Context Usage — {self.model or '(unknown model)'}")
        lines.append("")
        if self.ctx_limit:
            pct = self.used_tokens / self.ctx_limit * 100
            lines.append(
                f"  used {self.used_tokens // 1000}k / {self.ctx_limit // 1000}k tokens "
                f"({pct:.0f}%)"
            )
            lines.append(f"  {_bar(pct, width=40)}")
        else:
            lines.append(f"  used {self.used_tokens} tokens · ctx limit unknown")
        lines.append("")
        lines.append("Estimated breakdown:")
        label_width = max(len(s.name) for s in self.segments)
        lines.extend(s.render(label_width=label_width) for s in self.segments)
        return "\n".join(lines)


def _bar(percent: float, *, width: int) -> str:
    """ASCII progress bar — full block for filled portion, light block
    for the rest. Designed for monospace terminals; renders the same
    whether or not the terminal claims Unicode support."""
    percent = max(0.0, min(100.0, percent))
    filled = int(round(width * percent / 100))
    return "█" * filled + "░" * (width - filled)


def build(
    *,
    model: str,
    ctx_limit: int,
    system_prompt: str,
    tools_schema_text: str,
    overview_text: str,
    recall_text: str,
    history_text: str,
) -> ContextReport:
    """Materialise a ContextReport from the raw building blocks of a
    turn. All inputs are strings — the caller pre-stringifies anything
    structural (tools schema JSON-serialise, history join). Keeps this
    module free of Session/AgentState/JSON internals.

    `free space` is computed as `ctx_limit - sum(segment tokens)`; if
    that would go negative (e.g. history overflows the limit before
    /compact) we clamp to 0 so the row stays positive — the headline
    "used" number already signals over-budget.
    """
    sys_tokens = _tokens(system_prompt)
    tools_tokens = _tokens(tools_schema_text)
    overview_tokens = _tokens(overview_text)
    recall_tokens = _tokens(recall_text)
    history_tokens = _tokens(history_text)
    used = sys_tokens + tools_tokens + overview_tokens + recall_tokens + history_tokens
    free = max(0, ctx_limit - used) if ctx_limit else 0

    def pct(t: int) -> float | None:
        if not ctx_limit:
            return None
        return t / ctx_limit * 100

    segments: list[ContextSegment] = [
        ContextSegment("System prompt", sys_tokens, pct(sys_tokens)),
        ContextSegment("Tools schema", tools_tokens, pct(tools_tokens)),
        ContextSegment("Overview", overview_tokens, pct(overview_tokens)),
        ContextSegment("Memory recall", recall_tokens, pct(recall_tokens)),
        ContextSegment("Conversation", history_tokens, pct(history_tokens)),
    ]
    if ctx_limit:
        segments.append(ContextSegment("Free space", free, pct(free)))
    return ContextReport(
        model=model,
        ctx_limit=ctx_limit,
        used_tokens=used,
        segments=tuple(segments),
    )
