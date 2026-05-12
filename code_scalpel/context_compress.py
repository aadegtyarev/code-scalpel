"""Cross-turn tool-result compression.

When the model calls `read_file` on a large file in turn N, the raw output
sits in conversation history through turns N+1, N+2, N+3… By turn N+3 the
model has already distilled what it needed from that output into its own
reply; the raw bytes are dead weight on the context budget.

This module supplies the pure logic — predicate + marker formatter —
isolated from the agent so it can be unit-tested without the LLM
round-trip machinery. The agent (see `_compress_old_tool_results`) is
responsible for walking history and deciding which messages to feed in.

Marker shape:

    [compressed: <tool>(<args>) → N lines / M chars, see turn K | <hint>]

The hint preserves the most-load-bearing piece of typical tool output so
the model still has a breadcrumb pointing at what was there. Two ways
to produce it:
  • deterministic (default) — first non-empty line of the original output;
  • LLM-driven (`agent.compress_with_llm`) — one-line summary from the
    same model that runs the turn, generated via `summarize_with_llm`.
    Useful when the first line is something generic like `OK` or a
    table header; an LLM summary distills the actual result.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from code_scalpel.llm.adapter import LLMAdapter

# Cap on the hint inside a marker. Long pytest banners or multi-screen
# grep headers would otherwise re-bloat the very message we just
# compressed. ~100 chars keeps the marker single-line in most terminals
# while still carrying enough signal to recognise.
_HINT_MAX_CHARS = 100

_SUMMARIZE_PROMPT = (
    "Summarize the following tool output in ONE LINE (max 100 chars). "
    "Focus on the RESULT — a path, a verdict, a count, the key fact. "
    "No preamble, no quoting, no closing punctuation. If the output "
    "has no useful signal, reply with an empty string.\n\n"
    "Tool output:\n{content}"
)


def should_compress(
    content: str,
    age_turns: int,
    *,
    threshold_turns: int,
    min_chars: int,
) -> bool:
    """Return True iff this tool message is old enough AND fat enough to
    warrant compression.

    - `age_turns` strictly greater than `threshold_turns` — a message
      from the most recent N turns is still actively load-bearing for
      the model's current train of thought.
    - `min_chars` — short outputs (pytest "0 failed", a one-line grep
      hit) are already as compressed as a marker would be; rewriting
      them just churns history without saving tokens.
    - Idempotency — content that already starts with the marker prefix
      is short-circuited. Otherwise repeated turns would prepend
      `[compressed: ...]` markers ad infinitum.
    """
    if age_turns <= threshold_turns:
        return False
    if len(content) < min_chars:
        return False
    # Idempotency — content already wearing the marker prefix gets
    # short-circuited; otherwise repeated turns nest markers in markers.
    return not content.lstrip().startswith("[compressed:")


def compress_tool_message(
    content: str,
    tool_name: str,
    args_summary: str,
    turn: int,
    *,
    hint: str | None = None,
) -> str:
    """Build the compression marker for one tool message.

    Stats (`N lines / M chars`) come from the ORIGINAL content — the
    marker is metadata about what got dropped, not about itself.

    Hint resolution:
      • `hint=None` (default) — use the first non-empty line of `content`,
        truncated to `_HINT_MAX_CHARS` with an ellipsis suffix;
      • `hint=""` — caller decided there's no useful signal; omit the
        hint segment entirely so we don't emit a dangling `| ` separator;
      • `hint="..."` — caller supplied a custom hint (e.g. an LLM summary
        via `summarize_with_llm`); use it verbatim, truncated to fit.
    """
    line_count = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
    char_count = len(content)
    resolved_hint = hint if hint is not None else _first_nonempty_line(content)
    if resolved_hint and len(resolved_hint) > _HINT_MAX_CHARS:
        resolved_hint = resolved_hint[: _HINT_MAX_CHARS - 1] + "…"
    base = f"[compressed: {tool_name}({args_summary}) → {line_count} lines / {char_count} chars, see turn {turn}"
    if resolved_hint:
        return f"{base} | {resolved_hint}]"
    return f"{base}]"


async def summarize_with_llm(content: str, llm: LLMAdapter) -> str:
    """One-line summary of `content` from `llm`. Returns "" on any
    failure (network, malformed reply, empty) — callers treat "" as
    "no LLM hint, fall back to first-non-empty-line".

    The wrapping prompt is intentionally tight: weak local models drift
    into prose if given any slack. Even so, we strip the reply to its
    first non-empty line so a multi-line answer collapses cleanly into
    a single-line marker."""
    try:
        response = await llm.chat(
            [{"role": "user", "content": _SUMMARIZE_PROMPT.format(content=content)}],
            temperature=0.1,
            max_tokens=80,
        )
    except Exception:
        return ""
    text = (response.content or "").strip()
    if not text:
        return ""
    # Collapse to first non-empty line — a chatty model that returned
    # "Here's the summary:\nfoo\n" still gives us a usable single line.
    return _first_nonempty_line(text)


def _first_nonempty_line(content: str) -> str:
    """Return the first non-empty line, stripped and truncated. Empty
    string when content has no usable line — caller decides whether to
    omit the hint segment."""
    for raw in content.splitlines():
        line = raw.strip()
        if not line:
            continue
        if len(line) > _HINT_MAX_CHARS:
            return line[: _HINT_MAX_CHARS - 1] + "…"
        return line
    return ""
