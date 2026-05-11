"""Compose parser + walker into a `FileIndex` for one file.

Phase 2 will swap project_map.py consumers to call this; Phase 1 keeps the
two paths in parallel so we can A/B without risking regressions in the TUI.
"""

from __future__ import annotations

from pathlib import Path

from code_scalpel.index.model import FileIndex
from code_scalpel.index.walkers import walk_python


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
    internal = _internal_packages(root)
    symbols, imports = walk_python(source_bytes, internal=internal)
    loc = source_bytes.count(b"\n")
    if source_bytes and not source_bytes.endswith(b"\n"):
        loc += 1
    return FileIndex(
        rel_path=rel_path,
        symbols=symbols,
        imports=imports,
        loc=loc,
    )


def _internal_packages(root: Path) -> frozenset[str]:
    """Same shape as `project_map._internal_packages`.

    Duplicated rather than imported so this package stays self-contained for
    the Phase 2 cutover (when project_map.py goes away, nothing in `index/`
    breaks). Cheap: one `iterdir`.
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
