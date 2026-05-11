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
    `signature` is the rendered `def name(args) -> ret` for functions and
    methods (empty string for classes — they have no call signature).
    """

    name: str
    kind: SymbolKind
    qualified_name: str
    lineno: int
    end_lineno: int
    docstring: str
    signature: str = ""


@dataclass(frozen=True)
class Constant:
    """One top-level uppercase assignment in a file (`API_URL = ...`).

    Surfaced separately from `Symbol` because constants don't have a kind,
    qualified name, or docstring — they're just a marker that "this name
    is a module-level configuration value". Used by the project map to
    render the same `NAME = ...` lines the old ast walker produced.
    """

    name: str
    lineno: int


@dataclass(frozen=True)
class FileIndex:
    """Parsed view of a single Python file.

    `parse_error` is True when tree-sitter encountered any error nodes in
    the parse tree — symbols/imports may still be partial. Lets the
    project map render the `parse error` footer without re-parsing via
    ast.
    """

    rel_path: str
    symbols: tuple[Symbol, ...]
    imports: tuple[str, ...]
    loc: int
    constants: tuple[Constant, ...] = ()
    parse_error: bool = False
