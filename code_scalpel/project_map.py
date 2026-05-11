"""Compact project map for LLM context.

Goal: replace "list 200 files + dump 3 of them whole" with a structural map
the model can scan for free. Each Python file contributes a one-line header
plus its top-level symbols (classes, functions) with signatures. Non-Python
files contribute just a path + line count.

The map is what the model sees by default; on-demand `read_file` tool calls
fetch full content of any single file when actually needed.

Roughly: a 30-file project that used to need 6-8k tokens of eager context
becomes 0.5-1.5k.

Phase 3 cutover: this module is now a thin rendering shim plus the
lightweight `build_map_overview` (pure line counts — no parsing involved).
Every Python-aware path goes through `code_scalpel.index.build_file_index`,
which is tree-sitter under the hood. No `ast` here.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from code_scalpel.index import FileIndex, build_file_index
from code_scalpel.tools.files import list_files

_INDEX_FILE = Path(".code-scalpel") / "INDEX.json"


def build_map(root: Path, max_files: int = 200, use_cache: bool = True) -> str:
    """Return a compact textual map of the project rooted at `root`.

    With `use_cache=True`, persists per-file blocks keyed by mtime so unchanged
    files don't get re-parsed on every turn. Massive win on larger projects.

    This is the FULL map — every file with signatures, docstrings, imports.
    For per-turn context use `build_map_overview` and let the model drill in
    via the `map_file` tool. The full map is what `/map` slash and the
    initial-turn context use.
    """
    files = list_files(root, max_files=max_files)
    cache = _load_cache(root) if use_cache else {}
    new_cache: dict[str, dict[str, float | str]] = {}
    blocks: list[str] = []
    for rel in files:
        path = root / rel
        rel_key = str(rel)
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        cached = cache.get(rel_key)
        if cached is not None and cached.get("mtime") == mtime:
            block = str(cached["block"])
        else:
            if rel.suffix == ".py":
                idx = build_file_index(root, rel_key)
                block = _render_python_block(rel_key, idx, path)
            else:
                block = _plain_block(rel_key, path)
        new_cache[rel_key] = {"mtime": mtime, "block": block}
        blocks.append(block)
    if use_cache:
        _save_cache(root, new_cache)
    return "\n".join(blocks)


def build_map_overview(root: Path, max_files: int = 200) -> str:
    """Lightweight per-turn map: just paths + line counts, no symbols.

    The model gets a project skeleton it can navigate. For any file it
    actually needs to reason about, it calls the `map_file(path)` tool
    which returns the full block (signatures + docstrings + imports).

    Token budget on a 50-file project: ~1500 chars / ~375 tokens (vs
    the full map's ~14k tokens). Same ceiling for projects 10× larger.
    """
    files = list_files(root, max_files=max_files)
    lines: list[str] = []
    for rel in files:
        path = root / rel
        try:
            n = sum(1 for _ in path.open("rb")) if path.is_file() else 0
        except OSError:
            continue
        lines.append(f"{rel} [{n}L]")
    return "\n".join(lines)


def build_file_map(root: Path, rel_path: str) -> str:
    """Full symbol map for ONE file. Backs the `map_file` agent tool.

    Returns the same per-file block format `build_map` would produce
    (path header + imports + signatures + docstrings), or a single-line
    error if the file is missing / not Python / unreadable.
    """
    target = root / rel_path
    if not target.is_file():
        return f"{rel_path}: file not found"
    if target.suffix != ".py":
        # Non-Python: just give the line count
        try:
            n = sum(1 for _ in target.open("rb"))
        except OSError:
            return f"{rel_path}: unreadable"
        return f"{rel_path} [{n}L]"
    idx = build_file_index(root, rel_path)
    if idx is None:
        return f"{rel_path}: unreadable"
    if idx.parse_error:
        return f"{rel_path} [{idx.loc}L, parse error]"
    return _render_file_block(idx)


@dataclass(frozen=True)
class Definition:
    """One symbol definition site discovered by `find_definitions`.

    `kind` is one of `class`, `function`, `method`, `async function`,
    `async method` — enough for the agent's "where is X?" answer to
    say *what* X is without re-reading the file. `line` is 1-based to
    match every editor and pytest in the world.
    """

    rel_path: str
    line: int
    kind: str
    qualified_name: str  # "ClassName.method" or just "function_name"


def find_definitions(root: Path, name: str, *, max_files: int = 200) -> list[Definition]:
    """Walk every Python file under `root` and return all definition
    sites whose top-level identifier matches `name`. Looks at classes,
    top-level functions, and methods — anything else (variables,
    constants) would balloon the result set without much value for the
    agent's "where is X defined?" use case.

    Returns matches in deterministic order (file walk order from
    list_files, then class-internal order). Empty list when nothing
    matched — caller decides if that's a not-found message or a hint
    to call `grep` for a wider search.
    """
    if not name:
        return []
    out: list[Definition] = []
    files = list_files(root, max_files=max_files)
    for rel in files:
        if rel.suffix != ".py":
            continue
        idx = build_file_index(root, str(rel))
        if idx is None:
            continue
        for sym in idx.symbols:
            if sym.name == name:
                out.append(
                    Definition(
                        rel_path=str(rel),
                        line=sym.lineno,
                        kind=sym.kind,
                        qualified_name=sym.qualified_name,
                    )
                )
    return out


@dataclass(frozen=True)
class Reference:
    """One textual reference site found by `find_references`.

    Intentionally textual rather than AST-based: imports, comments,
    docstrings, string literals — they all count as "where X gets
    mentioned in this project". Models routinely ask "where is X
    used" expecting that grep-level answer. AST-only resolution would
    miss the comment in `# TODO: stop calling X here` that the user
    explicitly wants surfaced.
    """

    rel_path: str
    line: int
    text: str


_TEXT_SUFFIXES: frozenset[str] = frozenset(
    {
        ".py",
        ".pyi",
        ".md",
        ".rst",
        ".txt",
        ".toml",
        ".cfg",
        ".ini",
        ".yaml",
        ".yml",
        ".json",
        ".html",
        ".css",
        ".scss",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".go",
        ".rs",
        ".sh",
        ".bash",
        ".zsh",
        ".sql",
        ".tcss",
        ".env",
    }
)
_MAX_REFERENCE_BYTES = 2 * 1024 * 1024  # 2 MB — anything larger is data, not code


def find_references(
    root: Path,
    name: str,
    *,
    max_files: int = 200,
    max_results: int = 50,
) -> list[Reference]:
    """Scan the project for word-bounded matches of `name`. Skips
    binary-looking files (suffix allowlist + a 2 MB size cap), and the
    same paths `list_files` filters out (gitignore + hidden dirs).
    Results are truncated to `max_results` — for "where is X used",
    anything past ~50 hits is noise the user has to scroll through.

    The suffix allowlist is the cheap pre-filter; the byte cap is the
    backstop for a `.txt` that happens to be a 50 MB fixture or log.
    A binary-detected file would otherwise be read with
    `errors="replace"`, materialise tens of MB of replacement
    characters in memory, and emit bogus "matches" inside image bytes.
    """
    if not name:
        return []
    pattern = re.compile(rf"\b{re.escape(name)}\b")
    out: list[Reference] = []
    files = list_files(root, max_files=max_files)
    for rel in files:
        if rel.suffix and rel.suffix.lower() not in _TEXT_SUFFIXES:
            continue
        path = root / rel
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size > _MAX_REFERENCE_BYTES:
            continue
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                out.append(Reference(str(rel), i, line.rstrip()))
                if len(out) >= max_results:
                    return out
    return out


def _load_cache(root: Path) -> dict[str, dict[str, float | str]]:
    path = root / _INDEX_FILE
    if not path.is_file():
        return {}
    try:
        return dict(json.loads(path.read_text()))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_cache(root: Path, data: dict[str, dict[str, float | str]]) -> None:
    target = root / _INDEX_FILE
    try:
        target.parent.mkdir(exist_ok=True)
        target.write_text(json.dumps(data))
    except OSError:
        pass


def _render_python_block(rel_key: str, idx: FileIndex | None, path: Path) -> str:
    """Render the per-file block for `build_map`.

    `idx` is None only when the file is unreadable / non-Python — the
    caller already routed non-Python through `_plain_block`, so we just
    fall back to a line-count header. Parse errors yield a `parse error`
    footer (same shape the ast path produced).
    """
    if idx is None:
        loc = _loc_of(path)
        return f"{rel_key} [{loc}L]"
    if idx.parse_error:
        return f"{rel_key} [{idx.loc}L, parse error]"
    return _render_file_block(idx)


def _render_file_block(idx: FileIndex) -> str:
    """Render the per-file block from a `FileIndex`.

    All data — symbols with signatures + docstrings, imports, constants —
    comes from the index. The block layout matches what the ast renderer
    produced character-for-character, so cached blocks stay compatible.
    """
    parts: list[str] = [f"{idx.rel_path} [{idx.loc}L]"]
    if idx.imports:
        parts.append(f"  imports: {', '.join(idx.imports)}")
    # Source-order assembly: symbols + constants share the indent contract
    # (top-level → 2 spaces, methods → 4 spaces).
    entries: list[tuple[int, str]] = []
    for sym in idx.symbols:
        line = _render_index_symbol(sym)
        if line:
            entries.append((sym.lineno, line))
    for const in idx.constants:
        entries.append((const.lineno, f"  {const.name} = ..."))
    entries.sort(key=lambda e: e[0])
    parts.extend(line for _, line in entries)
    return "\n".join(parts)


def _render_index_symbol(sym: object) -> str:
    """Render a single Symbol row. Empty string drops the row.

    Top-level functions and classes get 2-space indent, methods get
    4-space (matches old _python_block). Docstrings come in as the first
    sentence (capped at 100 chars by the walker), appended after `  #`.
    """
    # `sym` typed loosely so we don't have to import Symbol just for the
    # cast — the FileIndex.symbols tuple already constrains the input.
    kind = getattr(sym, "kind", "")
    name = getattr(sym, "name", "")
    docstring = getattr(sym, "docstring", "")
    signature = getattr(sym, "signature", "")
    if kind == "class":
        line = f"class {name}"
        if docstring:
            line += f"  # {docstring}"
        return f"  {line}"
    is_method = kind in ("method", "async method")
    if not signature:
        return ""
    sig = signature
    if docstring:
        sig += f"  # {docstring}"
    indent = "    " if is_method else "  "
    return f"{indent}{sig}"


def _plain_block(rel: str, path: Path) -> str:
    return f"{rel} [{_loc_of(path)}L]"


def _loc_of(path: Path) -> int:
    try:
        return sum(1 for _ in path.open("rb"))
    except OSError:
        return 0
