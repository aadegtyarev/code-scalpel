"""Custom Rich highlighter for the project_map format.

The map isn't valid Python (it mixes file headers with truncated symbol
signatures), so no Pygments lexer fits. This file paints the structurally
meaningful parts ourselves:

    code_scalpel/agent.py [314L]      ← file path + line-count marker
      class StepAgent                  ← class keyword
        def ask(self, task: str)       ← def keyword
        async def stream_ask(...)      ← async def keyword
"""

from __future__ import annotations

import re

from rich.text import Text

# File path at column 0: at least one slash or dot-and-extension, followed
# by whitespace. Anchored to line start via MULTILINE.
_PATH_RE = re.compile(r"^[\w./_-]+\.[\w]+(?=\s)", re.MULTILINE)
# Line-count marker like [21L] or [21L, parse error]
_LOC_RE = re.compile(r"\[\d+L[^\]]*\]")
# Top-level keywords we want to colour
_KW_RE = re.compile(r"\b(async def|def|class)\b")
# Module-level constants (UPPER_SNAKE = ...) the map shows
_CONST_RE = re.compile(r"^\s*([A-Z_][A-Z0-9_]+)(?=\s*=)", re.MULTILINE)


def highlight_map(raw: str) -> Text:
    """Return a Rich Text with the map structure coloured.

    Colours mirror the TUI's mode palette so the modal feels consistent
    with the rest of the chat:
        teal/cyan — file paths
        gold      — class / def keywords
        dim       — [NL] markers, constants
    """
    text = Text(raw, no_wrap=False)
    for m in _PATH_RE.finditer(raw):
        text.stylize("bold #6bc8d4", m.start(), m.end())
    for m in _LOC_RE.finditer(raw):
        text.stylize("dim #707070", m.start(), m.end())
    for m in _KW_RE.finditer(raw):
        text.stylize("bold #d4a050", m.start(), m.end())
    for m in _CONST_RE.finditer(raw):
        text.stylize("#7fc090", m.start(1), m.end(1))
    return text
