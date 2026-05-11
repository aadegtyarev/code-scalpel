"""Extract Mermaid fenced blocks from assistant replies.

Цель — отделить чисто-логическую часть (regex по тексту ответа модели)
от Textual-виджета `MermaidCard`. `agent.py` остаётся нетронутым: app.py
прогоняет финальный текст через `extract_mermaid_blocks` после
`extract_edits` и решает, что отрисовать.
"""

from __future__ import annotations

import re

# ```mermaid\n...\n``` — нестрогая закрывающая граница (если модель не
# закрыла fence — блок просто не подхватывается, без падений). DOTALL
# чтобы `.` ловил переводы строк внутри тела блока.
_MERMAID_FENCE_RE = re.compile(
    r"```mermaid[ \t]*\n(?P<body>.*?)\n```",
    re.DOTALL,
)


def extract_mermaid_blocks(text: str) -> list[str]:
    """Return the source of each ```mermaid ... ``` block in *text*.

    Empty input, no blocks, malformed (unclosed) fence — all return
    an empty list rather than raising. Python / other language fences
    are skipped: only `mermaid` matches.
    """
    if not text:
        return []
    return [m.group("body") for m in _MERMAID_FENCE_RE.finditer(text)]


__all__ = ["extract_mermaid_blocks"]
