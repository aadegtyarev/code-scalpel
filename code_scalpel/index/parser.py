"""Process-wide tree-sitter Parser singleton for Python.

Parser construction is cheap but the Language capsule comes from a C
extension and there's no point re-binding it on every call. lru_cache gives
us lazy init + thread-safe memoisation in one line.

The plan flagged `tree-sitter-language-pack` 1.8.0 as broken (returned empty
docstrings for project_map.py). We use the individual `tree-sitter-python`
package instead — same Language source, no aggregator layer.
"""

from __future__ import annotations

from functools import lru_cache

import tree_sitter_python as tspython
from tree_sitter import Language, Parser


@lru_cache(maxsize=1)
def python_language() -> Language:
    return Language(tspython.language())


@lru_cache(maxsize=1)
def python_parser() -> Parser:
    return Parser(python_language())
