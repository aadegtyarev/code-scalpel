from __future__ import annotations

from pathlib import Path

import pathspec


def _load_gitignore(root: Path) -> pathspec.PathSpec:  # type: ignore[type-arg]
    gitignore = root / ".gitignore"
    patterns = [".git/"]
    if gitignore.is_file():
        patterns += gitignore.read_text().splitlines()
    return pathspec.PathSpec.from_lines("gitignore", patterns)


def list_files(root: Path, max_files: int = 200) -> list[Path]:
    """Return relative paths of tracked files under root, respecting .gitignore."""
    spec = _load_gitignore(root)
    result: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if not spec.match_file(str(rel)):
            result.append(rel)
        if len(result) >= max_files:
            break
    return result


_TRUNCATED = "\n... ({remaining} more lines, showing first {shown})"


def read_file(path: Path, max_lines: int = 400) -> str:
    """Read file content, truncating at max_lines with a note."""
    lines = path.read_text(errors="replace").splitlines()
    if len(lines) <= max_lines:
        return "\n".join(lines)
    shown = lines[:max_lines]
    note = _TRUNCATED.format(remaining=len(lines) - max_lines, shown=max_lines)
    return "\n".join(shown) + note
