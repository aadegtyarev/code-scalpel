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

    [compressed: <tool>(<args>) → N lines / M chars, see turn K | <first-line hint>]

The first-line hint preserves the most-load-bearing piece of typical tool
output (a path, a pytest verdict, a grep header) so the model still has a
breadcrumb pointing at what was there.
"""

from __future__ import annotations

# Cap on the first-line hint inside a marker. Long pytest banners or
# multi-screen grep headers would otherwise re-bloat the very message we
# just compressed. ~100 chars keeps the marker single-line in most
# terminals while still carrying enough signal to recognise.
_HINT_MAX_CHARS = 100


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
) -> str:
    """Build the compression marker for one tool message.

    Stats (`N lines / M chars`) come from the ORIGINAL content — the
    marker is metadata about what got dropped, not about itself. The
    first non-empty line is preserved as a hint (truncated to
    `_HINT_MAX_CHARS` with an ellipsis suffix); if no non-empty line
    exists, the hint segment is omitted entirely so we don't emit
    a dangling `| ` separator.
    """
    line_count = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
    char_count = len(content)
    hint = _first_nonempty_line(content)
    base = f"[compressed: {tool_name}({args_summary}) → {line_count} lines / {char_count} chars, see turn {turn}"
    if hint:
        return f"{base} | {hint}]"
    return f"{base}]"


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
