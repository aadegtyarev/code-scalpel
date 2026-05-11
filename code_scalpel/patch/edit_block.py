"""SEARCH/REPLACE edit-block format — aider's format, much friendlier to weak
local models than unified diff (no line counters, no @@ headers).

Format (single edit):

    path/to/file.py
    ```python
    <<<<<<< SEARCH
    <exact existing lines>
    =======
    <replacement lines>
    >>>>>>> REPLACE
    ```

Empty SEARCH = create new file. Empty REPLACE = delete chunk.
Multiple edits = multiple blocks back-to-back.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_HEAD = "<<<<<<< SEARCH"
_SEP = "======="
_TAIL = ">>>>>>> REPLACE"

# matches: optional fence + SEARCH + body + ======= + body + REPLACE
_BLOCK_RE = re.compile(
    r"(?:^```[a-zA-Z]*\n)?"
    r"<<<<<<< SEARCH\n"
    r"(?P<search>.*?)"
    r"^=======\n"
    r"(?P<replace>.*?)"
    r"^>>>>>>> REPLACE",
    re.DOTALL | re.MULTILINE,
)


@dataclass(frozen=True)
class Edit:
    path: str
    search: str  # empty = create new file
    replace: str  # empty = delete the matched block


def extract_edits(text: str) -> list[Edit]:
    """Parse SEARCH/REPLACE blocks out of an LLM response. Returns [] if none.

    When multiple blocks target the same file, only the first one needs a path
    line — subsequent blocks inherit the previous path.
    """
    edits: list[Edit] = []
    last_path: str | None = None
    last_end = 0
    for m in _BLOCK_RE.finditer(text):
        path = _path_before(text, last_end, m.start())
        if path is None:
            path = last_path
        if path is None:
            continue
        edits.append(Edit(path=path, search=m.group("search"), replace=m.group("replace")))
        last_path = path
        last_end = m.end()
    return edits


_FENCE_LINE = re.compile(r"^```[a-zA-Z]*$")
_BLOCK_MARKERS = ("<<<<<<<", "=======", ">>>>>>>")


def _path_before(text: str, after: int, before: int) -> str | None:
    """Find a file-path line in text[after:before]. Returns None if no plain
    path-looking line is present (then the caller should inherit the previous
    block's path)."""
    segment = text[after:before]
    for line in reversed(segment.splitlines()):
        s = line.strip()
        if not s:
            continue
        if _FENCE_LINE.match(s) or s.startswith("```"):
            continue
        if any(s.startswith(m) for m in _BLOCK_MARKERS):
            continue
        s = s.strip("`*_ ")
        if s and not any(s.startswith(m) for m in _BLOCK_MARKERS):
            return s
    return None


# ── applier cascade ──────────────────────────────────────────────────────────


def apply_edits(edits: list[Edit], root: Path) -> tuple[bool, str]:
    """Apply all edits atomically. Returns (ok, error_message)."""
    if not edits:
        return False, "no edits to apply"

    pending: dict[Path, str | None] = {}
    for e in edits:
        path = root / e.path
        if not e.search.strip():
            # Empty SEARCH: create a new file, or prepend if the file already
            # exists. The model emits empty SEARCH for "add import at top of
            # this file" — overwriting would destroy the file content.
            prepend = e.replace
            if prepend and not prepend.endswith("\n"):
                prepend += "\n"
            if path in pending and pending[path] is not None:
                pending[path] = prepend + (pending[path] or "")
            elif path.exists():
                pending[path] = prepend + path.read_text()
            else:
                pending[path] = e.replace
            continue
        if path not in pending:
            if not path.exists():
                return False, f"{e.path}: file not found for SEARCH block"
            pending[path] = path.read_text()
        current = pending[path]
        if current is None:
            current = ""
        new = _apply_one(current, e.search, e.replace)
        if new is None:
            return False, _no_match_error(e, current)
        pending[path] = new

    for path, content in pending.items():
        if content is None:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return True, ""


def _apply_one(source: str, search: str, replace: str) -> str | None:
    """Try increasingly-tolerant strategies, in aider's order."""
    # 1. Perfect match
    if search in source:
        return source.replace(search, replace, 1)

    # 2. Uniform leading-whitespace mismatch (model dropped indentation)
    fixed = _try_whitespace_outdent(source, search, replace)
    if fixed is not None:
        return fixed

    # 3. Strip spurious leading blank line from SEARCH (aider issue #25)
    if search.startswith("\n"):
        stripped = search[1:]
        if stripped and stripped in source:
            return source.replace(stripped, replace, 1)

    return None


def _try_whitespace_outdent(source: str, search: str, replace: str) -> str | None:
    """If SEARCH has uniform extra-or-missing indentation vs source, re-align it."""
    search_lines = search.splitlines(keepends=True)
    if not search_lines:
        return None

    # Outdent both SEARCH and REPLACE by their common leading whitespace prefix
    common = _common_leading_ws(search_lines)
    if common:
        search_out = "".join(
            ln[len(common) :] if ln.startswith(common) else ln for ln in search_lines
        )
    else:
        search_out = search

    # Search for outdented form in source; if found, learn the file's indent
    idx = source.find(search_out)
    if idx == -1:
        # Try ADDING indentation in front of every line (model over-outdented)
        for indent in _candidate_indents(source):
            candidate = "".join(indent + ln for ln in search_lines)
            if candidate in source:
                replace_lines = replace.splitlines(keepends=True)
                replaced = "".join(indent + ln for ln in replace_lines)
                return source.replace(candidate, replaced, 1)
        return None

    # Found outdented version — work out the file's true indent at that position
    # by looking at the first matched line.
    line_start = source.rfind("\n", 0, idx) + 1
    file_indent = source[line_start:idx]
    replace_lines = replace.splitlines(keepends=True)
    if common:
        replace_out = "".join(
            ln[len(common) :] if ln.startswith(common) else ln for ln in replace_lines
        )
    else:
        replace_out = replace
    replace_with_indent = "".join(
        file_indent + ln if ln.strip() else ln for ln in replace_out.splitlines(keepends=True)
    )
    return source.replace(file_indent + search_out, replace_with_indent, 1)


def _common_leading_ws(lines: list[str]) -> str:
    non_empty = [ln for ln in lines if ln.strip()]
    if not non_empty:
        return ""
    prefix = ""
    first = non_empty[0]
    for i, ch in enumerate(first):
        if ch not in (" ", "\t"):
            break
        candidate = first[: i + 1]
        if all(ln.startswith(candidate) for ln in non_empty):
            prefix = candidate
        else:
            break
    return prefix


def _candidate_indents(source: str) -> list[str]:
    """Distinct leading whitespace prefixes seen in source — likely valid indents."""
    seen: set[str] = set()
    for line in source.splitlines():
        if not line.strip():
            continue
        ws = line[: len(line) - len(line.lstrip())]
        if ws:
            seen.add(ws)
    # Order shortest first so we don't over-indent prematurely
    return sorted(seen, key=len)


def _no_match_error(edit: Edit, source: str) -> str:
    return f"SEARCH block did not match {edit.path}. Source has {len(source.splitlines())} lines."


# ── synthesis for display ────────────────────────────────────────────────────


def edits_to_diff(edits: list[Edit], root: Path) -> str:
    """Synthesize a unified-diff-like string for UI display. Read-only."""
    chunks: list[str] = []
    for e in edits:
        chunks.append(f"--- a/{e.path}\n+++ b/{e.path}\n")
        for line in e.search.splitlines():
            chunks.append(f"-{line}\n")
        for line in e.replace.splitlines():
            chunks.append(f"+{line}\n")
    return "".join(chunks)
