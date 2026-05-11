"""Tree-sitter-backed project index.

Phase 3 cutover: this is the API project_map.py renders from. The walker
emits Symbols with rendered signatures + docstrings, the builder adds
constants + parse_error so consumers never need to touch ast.
"""

from code_scalpel.index.builder import build_file_index
from code_scalpel.index.model import Constant, FileIndex, Symbol, SymbolKind
from code_scalpel.index.shape import control_flow_shape
from code_scalpel.index.walkers import walk_python, walk_top_level_constants

__all__ = [
    "Constant",
    "FileIndex",
    "Symbol",
    "SymbolKind",
    "build_file_index",
    "control_flow_shape",
    "walk_python",
    "walk_top_level_constants",
]
