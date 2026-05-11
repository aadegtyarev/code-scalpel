"""Unit tests for `extract_mermaid_blocks` — pure regex logic over the
text of the assistant reply. No widgets, no shelling out."""

from __future__ import annotations

from code_scalpel.diagrams import extract_mermaid_blocks


def test_extract_empty_input_returns_empty_list() -> None:
    assert extract_mermaid_blocks("") == []


def test_extract_no_blocks_returns_empty_list() -> None:
    text = "Just a regular reply with no diagrams.\n\nHave a nice day."
    assert extract_mermaid_blocks(text) == []


def test_extract_one_block() -> None:
    text = "Here's a diagram:\n\n```mermaid\nflowchart TD\n    A --> B\n```\n\nThat's it."
    blocks = extract_mermaid_blocks(text)
    assert blocks == ["flowchart TD\n    A --> B"]


def test_extract_multiple_blocks_preserves_order() -> None:
    text = (
        "First:\n"
        "```mermaid\n"
        "graph LR\n"
        "    X --> Y\n"
        "```\n"
        "Second:\n"
        "```mermaid\n"
        "sequenceDiagram\n"
        "    Alice->>Bob: hi\n"
        "```\n"
    )
    blocks = extract_mermaid_blocks(text)
    assert blocks == [
        "graph LR\n    X --> Y",
        "sequenceDiagram\n    Alice->>Bob: hi",
    ]


def test_extract_malformed_fence_no_closer_returns_empty() -> None:
    """Если модель забыла закрыть fence — лучше пропустить блок,
    чем подхватить полтекста ответа. Никаких падений."""
    text = "```mermaid\nflowchart TD\n    A --> B\n\nLooks like I forgot to close."
    assert extract_mermaid_blocks(text) == []


def test_extract_mermaid_only_skips_python_fences() -> None:
    """Mixed reply: одна Python-сниппет, один mermaid. Только mermaid."""
    text = (
        "```python\n"
        "print('not a diagram')\n"
        "```\n"
        "And now a diagram:\n"
        "```mermaid\n"
        "flowchart TD\n"
        "    A --> B\n"
        "```\n"
    )
    blocks = extract_mermaid_blocks(text)
    assert blocks == ["flowchart TD\n    A --> B"]
