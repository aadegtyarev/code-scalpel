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


# Short notes per segment explaining what drives its size and what
# the user can DO about it — a human scanning /context wants to know
# "why is this big and can I shrink it?", not just the absolute number.
# Keys must match ContextSegment.name.
_SEGMENT_NOTES: dict[str, str] = {
    "System prompt": "static rules: identity, tone, grounding",
    "Tools schema": "function-calling schema for 6 tools",
    "Skills": "active test/lint/format contracts",
    "Recipes": "learned templates (learn --type recipe)",
    "Project files": "paths + line counts of cwd",
    "Memory recall": "top-3 hits from /remember notes",
    "Conversation": "history; shrinks via /compact and auto summaries",
    "Free space": "left for the next model reply",
}


@dataclass(frozen=True)
class ContextSegment:
    """One row in the breakdown — name, token estimate, percent of the
    model's context limit. Percent is None when no limit is known
    (autodetect hadn't finished or LM Studio didn't say)."""

    name: str
    tokens: int
    percent: float | None


@dataclass(frozen=True)
class ContextReport:
    model: str
    ctx_limit: int  # 0 when unknown
    used_tokens: int
    segments: tuple[ContextSegment, ...]

    def render(self) -> str:
        """Grouped layout:

          What's in context right now:
            ┌─ System prompt   2 062t (12.6%)   identity, tone, …
            ├─ Tools schema    1 166t  (7.1%)   function-calling …
            …
            └─ Conversation        0t  (0.0%)   grows per turn …
                          ─────
                    used  4 115t (25.1%)

          Available:
              Free space  12 269t (74.9%)   left for the next reply

        Pipes and box-drawing glyphs are stable Unicode every terminal
        renders. Numbers are right-padded so columns line up; one-line
        notes follow each row so it's clear WHAT and WHY at a glance.
        """
        used_segments = tuple(s for s in self.segments if s.name != "Free space")
        free_seg = next((s for s in self.segments if s.name == "Free space"), None)

        # Column widths — only for the "used" group; Free space is rendered
        # in a separate aligned block so its row doesn't widen the table.
        name_w = max((len(s.name) for s in used_segments), default=0)
        tokens_w = max((len(f"{s.tokens:,}") for s in used_segments), default=0)
        tokens_w = max(tokens_w, len(f"{self.used_tokens:,}"))

        lines: list[str] = []
        lines.append(f"Context Usage — {self.model or '(unknown model)'}")
        lines.append("")
        if self.ctx_limit:
            pct = self.used_tokens / self.ctx_limit * 100
            lines.append(
                f"used {self.used_tokens:,} / {self.ctx_limit:,} tokens ({pct:.0f}%)"
            )
            lines.append(_bar(pct, width=40))
        else:
            lines.append(f"used {self.used_tokens:,} tokens · ctx limit unknown")
        lines.append("")

        lines.append("What's in context right now:")
        last_idx = len(used_segments) - 1
        for i, seg in enumerate(used_segments):
            elbow = "└─" if i == last_idx else ("┌─" if i == 0 else "├─")
            tok = f"{seg.tokens:,}".rjust(tokens_w)
            name = seg.name.ljust(name_w)
            pct_part = f"({seg.percent:4.1f}%)" if seg.percent is not None else "(  ─  )"
            note = _SEGMENT_NOTES.get(seg.name, "")
            lines.append(f"  {elbow} {name}  {tok}t {pct_part}   {note}")
        # Subtotal under the group — explicit so the user doesn't have
        # to sum 5 rows by eye.
        rule = "─" * (tokens_w + 1)
        lines.append(f"     {' ' * name_w}  {rule}")
        if self.ctx_limit:
            tot_pct = self.used_tokens / self.ctx_limit * 100
            tot_pct_str = f"({tot_pct:4.1f}%)"
        else:
            tot_pct_str = "(  ─  )"
        lines.append(
            f"     {'used'.rjust(name_w)}  {self.used_tokens:,}".rjust(7 + name_w + tokens_w + 1)
            + f"t {tot_pct_str}"
        )

        if free_seg is not None:
            lines.append("")
            lines.append("Available:")
            free_tok = f"{free_seg.tokens:,}".rjust(tokens_w)
            free_pct = f"({free_seg.percent:4.1f}%)" if free_seg.percent is not None else ""
            free_note = _SEGMENT_NOTES.get("Free space", "")
            lines.append(
                f"     {free_seg.name.ljust(name_w)}  {free_tok}t {free_pct}   {free_note}"
            )
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
    skills_text: str = "",
    recipes_text: str = "",
) -> ContextReport:
    """Materialise a ContextReport from the raw building blocks of a
    turn. All inputs are strings — the caller pre-stringifies anything
    structural (tools schema JSON-serialise, history join). Keeps this
    module free of Session/AgentState/JSON internals.

    `skills_text` / `recipes_text` default to "" — SkillRegistry and
    `learn` artefacts don't reach the model prompt yet. The slots
    exist so once we wire them, the breakdown picks up the cost
    automatically without a render rewrite.

    `free space` is computed as `ctx_limit - sum(segment tokens)`; if
    that would go negative (e.g. history overflows the limit before
    /compact) we clamp to 0 so the row stays positive — the headline
    "used" number already signals over-budget.
    """
    sys_tokens = _tokens(system_prompt)
    tools_tokens = _tokens(tools_schema_text)
    skills_tokens = _tokens(skills_text)
    recipes_tokens = _tokens(recipes_text)
    overview_tokens = _tokens(overview_text)
    recall_tokens = _tokens(recall_text)
    history_tokens = _tokens(history_text)
    used = (
        sys_tokens
        + tools_tokens
        + skills_tokens
        + recipes_tokens
        + overview_tokens
        + recall_tokens
        + history_tokens
    )
    free = max(0, ctx_limit - used) if ctx_limit else 0

    def pct(t: int) -> float | None:
        if not ctx_limit:
            return None
        return t / ctx_limit * 100

    segments: list[ContextSegment] = [
        ContextSegment("System prompt", sys_tokens, pct(sys_tokens)),
        ContextSegment("Tools schema", tools_tokens, pct(tools_tokens)),
        ContextSegment("Skills", skills_tokens, pct(skills_tokens)),
        ContextSegment("Recipes", recipes_tokens, pct(recipes_tokens)),
        ContextSegment("Project files", overview_tokens, pct(overview_tokens)),
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
