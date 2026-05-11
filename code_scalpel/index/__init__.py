"""Tree-sitter-backed project index (Phase 1 — runs in parallel with project_map.py)."""

from code_scalpel.index.builder import build_file_index
from code_scalpel.index.model import FileIndex, Symbol, SymbolKind
from code_scalpel.index.shape import control_flow_shape
from code_scalpel.index.walkers import walk_python

__all__ = [
    "FileIndex",
    "Symbol",
    "SymbolKind",
    "build_file_index",
    "control_flow_shape",
    "walk_python",
]
