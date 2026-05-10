from __future__ import annotations

from pathlib import Path

import pathspec


def _load_gitignore(root: Path) -> pathspec.PathSpec:
    gitignore = root / ".gitignore"
    patterns = [".git/"]
    if gitignore.is_file():
        patterns += gitignore.read_text().splitlines()
    return pathspec.PathSpec.from_lines("gitwildmatch", patterns)


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


def read_file(path: Path, max_lines: int = 400) -> str:
    """Read file with line numbers for accurate patch generation.

    Format matches what the model needs to produce unified diffs:
        1  def hello():
        2      pass
    Truncates at max_lines with a note showing total line count.
    """
    lines = path.read_text(errors="replace").splitlines()
    total = len(lines)
    shown = lines[:max_lines]
    width = len(str(total))
    numbered = "\n".join(f"{i + 1:{width}}  {line}" for i, line in enumerate(shown))
    if total <= max_lines:
        return numbered
    return numbered + f"\n... ({total - max_lines} more lines, {total} total)"
