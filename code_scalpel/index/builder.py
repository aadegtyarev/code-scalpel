"""Compose parser + walker into a `FileIndex` for one file.

Phase 3 cutover: project_map.py's consumers (build_file_map, build_map,
find_definitions) all route here. The index carries everything they
need — signatures, docstrings, imports, constants, parse-error flag —
so project_map.py is pure rendering.
"""

from __future__ import annotations

from pathlib import Path

from code_scalpel.index.model import FileIndex
from code_scalpel.index.parser import python_parser
from code_scalpel.index.walkers import walk_python, walk_top_level_constants
from code_scalpel.workspace import internal_packages


def build_file_index(root: Path, rel_path: str) -> FileIndex | None:
    """Read `root / rel_path` and parse it into a `FileIndex`.

    Returns None for non-Python paths and for I/O failures — same skip-and-
    continue contract as `project_map.build_map`, which never raises on a
    bad file.
    """
    target = root / rel_path
    if target.suffix != ".py" or not target.is_file():
        return None
    try:
        source_bytes = target.read_bytes()
    except OSError:
        return None
    internal = internal_packages(root)
    symbols, imports = walk_python(source_bytes, internal=internal)
    constants = walk_top_level_constants(source_bytes)
    # `has_error` is set when tree-sitter encountered any ERROR or MISSING
    # node during recovery. That's the same signal ast.parse() raising
    # SyntaxError used to give us — the file didn't fully parse — but we
    # still got partial symbols out of the recovery, which is what we want
    # to render to the user.
    parse_error = python_parser().parse(source_bytes).root_node.has_error
    loc = source_bytes.count(b"\n")
    if source_bytes and not source_bytes.endswith(b"\n"):
        loc += 1
    return FileIndex(
        rel_path=rel_path,
        symbols=symbols,
        imports=imports,
        loc=loc,
        constants=constants,
        parse_error=parse_error,
    )
