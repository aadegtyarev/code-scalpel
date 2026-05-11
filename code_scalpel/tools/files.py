from __future__ import annotations

from pathlib import Path

import pathspec


def _load_gitignore(root: Path) -> pathspec.PathSpec:  # type: ignore[type-arg]
    gitignore = root / ".gitignore"
    patterns = [".git/", ".*/"]
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


def read_file(
    path: Path,
    max_lines: int = 400,
    *,
    start_line: int | None = None,
    end_line: int | None = None,
    find: str | None = None,
    context: int = 20,
) -> str:
    """Read a file's body with line numbers — full or sliced.

    Three modes, picked by which args you pass:

    1. **Whole file** (no slicing args): returns up to `max_lines`
       lines from the top, then `… N more lines, total T` footer.
    2. **Window**: `start_line` and/or `end_line` (both 1-based,
       inclusive). Anything missing extends to the file edge,
       capped at `max_lines` from `start_line`.
    3. **Find**: `find=<substring>` returns every line containing
       the substring plus `context` lines before and after each
       hit. Adjacent windows merge. Use to land on the exact
       region the user cares about (e.g. failing-test traceback's
       line number).

    Output always carries 1-based line numbers so the model can
    quote `path:N` accurately and the SEARCH text in patches lines
    up with the real source.
    """
    lines = path.read_text(errors="replace").splitlines()
    total = len(lines)
    width = len(str(total)) if total else 1

    def _fmt(slice_lines: list[tuple[int, str]]) -> str:
        return "\n".join(f"{n:{width}}  {line}" for n, line in slice_lines)

    if find is not None:
        hits = [i for i, line in enumerate(lines) if find in line]
        if not hits:
            return f"(no occurrences of {find!r} in {total} lines)"
        # Merge windows around each hit into non-overlapping spans.
        spans: list[tuple[int, int]] = []
        for h in hits:
            lo = max(0, h - context)
            hi = min(total, h + context + 1)
            if spans and lo <= spans[-1][1]:
                spans[-1] = (spans[-1][0], max(spans[-1][1], hi))
            else:
                spans.append((lo, hi))
        chunks: list[str] = []
        for lo, hi in spans:
            chunks.append(_fmt([(i + 1, lines[i]) for i in range(lo, hi)]))
        header = f"# {len(hits)} occurrence(s) of {find!r} in {total} lines"
        return header + "\n" + "\n…\n".join(chunks)

    if start_line is not None or end_line is not None:
        s = max(1, start_line or 1)
        e = end_line if end_line is not None else min(total, s + max_lines - 1)
        e = min(total, e)
        if s > total:
            return f"(start_line {s} is past end of file at line {total})"
        if s > e:
            return f"(empty range: start_line={s} > end_line={e})"
        # Window cap — keep big files from blowing context.
        if e - s + 1 > max_lines:
            e = s + max_lines - 1
        sliced = [(i + 1, lines[i]) for i in range(s - 1, e)]
        body = _fmt(sliced)
        remainder = total - e
        suffix = f"\n… ({remainder} more lines below, {total} total)" if remainder > 0 else ""
        prefix = f"# lines {s}-{e} of {total}\n" if s > 1 or e < total else ""
        return prefix + body + suffix

    shown = lines[:max_lines]
    numbered = "\n".join(f"{i + 1:{width}}  {line}" for i, line in enumerate(shown))
    if total <= max_lines:
        return numbered
    return numbered + f"\n… ({total - max_lines} more lines, {total} total)"
