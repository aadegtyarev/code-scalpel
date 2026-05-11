"""Shared lightweight workspace queries used by both the project map and
the tree-sitter index.

Phase 3 cutover: previously `_internal_packages` was duplicated in
`project_map.py` and `index/builder.py`. Both engines need to know which
top-level names belong to *this* project so they can filter import noise
(stdlib + third-party imports never trace flow within the codebase).
Moving it here keeps the dedup honest — one implementation, two callers.
"""

from __future__ import annotations

from pathlib import Path


def internal_packages(root: Path) -> frozenset[str]:
    """Top-level package/module names belonging to this project.

    A name is "internal" when:
      • it is a directory directly under `root` containing `__init__.py`
        (a Python package), or
      • it is a bare `*.py` file directly under `root` (single-file project
        — e.g. one `tool.py` at the root counts as its own namespace).

    Hidden directories (`.venv`, `.git`, etc.) lack `__init__.py` so they
    fall out naturally; we don't need an explicit allowlist.

    Returns `frozenset` so callers can freely share + cache the result.
    """
    names: set[str] = set()
    try:
        for child in root.iterdir():
            if child.is_dir() and (child / "__init__.py").is_file():
                names.add(child.name)
            elif child.is_file() and child.suffix == ".py":
                stem = child.stem
                if stem != "__init__":
                    names.add(stem)
    except OSError:
        pass
    return frozenset(names)
