"""Frozen value types emitted by the tree-sitter index walker.

These mirror what `project_map.py` extracts via `ast`, but with a wider shape
so Phase 2 can swap callers without losing information. Kept dependency-free
(no tree-sitter import here) so consumers can type against the model without
pulling in the parser.
"""

from __future__ import annotations

from dataclasses import dataclass

# `kind` is a closed string set; using Literal here would force the walkers to
# carry the same Literal around for every internal helper, which is more noise
# than the field is worth. Tests assert on the values directly.
SymbolKind = str


@dataclass(frozen=True)
class Symbol:
    """One top-level class, function, or method discovered in a file.

    `lineno` / `end_lineno` are 1-based to match editors and pytest output.
    `qualified_name` is `"ClassName.method"` for methods, bare name otherwise.
    `docstring` is the first-sentence summary capped at 100 chars (see
    `walkers._docstring_summary`).
    """

    name: str
    kind: SymbolKind
    qualified_name: str
    lineno: int
    end_lineno: int
    docstring: str


@dataclass(frozen=True)
class FileIndex:
    """Parsed view of a single Python file."""

    rel_path: str
    symbols: tuple[Symbol, ...]
    imports: tuple[str, ...]
    loc: int
