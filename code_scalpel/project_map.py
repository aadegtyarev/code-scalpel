"""Compact project map for LLM context.

Goal: replace "list 200 files + dump 3 of them whole" with a structural map
the model can scan for free. Each Python file contributes a one-line header
plus its top-level symbols (classes, functions) with signatures. Non-Python
files contribute just a path + line count.

The map is what the model sees by default; on-demand `read_file` tool calls
fetch full content of any single file when actually needed.

Roughly: a 30-file project that used to need 6-8k tokens of eager context
becomes 0.5-1.5k.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path

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
    internal = _internal_packages(root)
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
                try:
                    source = path.read_text(errors="replace")
                except OSError:
                    continue
                block = _python_block(rel_key, source, internal)
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
    error if the file is missing / not Python / unreadable."""
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
    try:
        source = target.read_text(errors="replace")
    except OSError:
        return f"{rel_path}: unreadable"
    internal = _internal_packages(root)
    return _python_block(rel_path, source, internal)


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
        path = root / rel
        try:
            source = path.read_text(errors="replace")
        except OSError:
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        out.extend(_definitions_in(tree, str(rel), name))
    return out


def _definitions_in(tree: ast.Module, rel: str, name: str) -> list[Definition]:
    out: list[Definition] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            if node.name == name:
                out.append(Definition(rel, node.lineno, "class", node.name))
            for m in node.body:
                if isinstance(m, ast.FunctionDef | ast.AsyncFunctionDef) and m.name == name:
                    prefix = "async method" if isinstance(m, ast.AsyncFunctionDef) else "method"
                    out.append(Definition(rel, m.lineno, prefix, f"{node.name}.{m.name}"))
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name:
            prefix = "async function" if isinstance(node, ast.AsyncFunctionDef) else "function"
            out.append(Definition(rel, node.lineno, prefix, node.name))
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


def _internal_packages(root: Path) -> frozenset[str]:
    """Top-level package/module names belonging to this project. Used to
    filter imports in the map so we surface intra-project dependencies
    (which trace flow) and drop stdlib / third-party noise (typing,
    pathlib, textual, pydantic — useful for tools, not for flow analysis).
    """
    names: set[str] = set()
    try:
        for child in root.iterdir():
            if child.is_dir() and (child / "__init__.py").is_file():
                names.add(child.name)
            elif child.is_file() and child.suffix == ".py":
                # bare-module project — e.g. a single foo.py at the root
                stem = child.stem
                if stem != "__init__":
                    names.add(stem)
    except OSError:
        pass
    return frozenset(names)


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


def _python_block(rel: str, source: str, internal: frozenset[str] = frozenset()) -> str:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        # Still useful — fall back to a plain line-count header
        loc = len(source.splitlines())
        return f"{rel} [{loc}L, parse error]"

    lines = source.splitlines()
    loc = len(lines)
    symbols = _top_level_symbols(tree, lines)
    header = f"{rel} [{loc}L]"
    parts: list[str] = [header]
    imports = _internal_imports(tree, internal)
    if imports:
        parts.append(f"  imports: {', '.join(imports)}")
    if symbols:
        parts.extend(f"  {s}" for s in symbols)
    return "\n".join(parts)


def _internal_imports(tree: ast.Module, internal: frozenset[str]) -> list[str]:
    """Return a deduplicated, ordered list of intra-project import targets.

    For `from foo.bar import Baz` where `foo` is internal → "foo.bar.Baz".
    For relative `from . import x` → "x" (root-relative not resolved here).
    External / stdlib imports skipped — this list is for tracing flow.
    """
    seen: list[str] = []

    def _add(label: str) -> None:
        if label not in seen:
            seen.append(label)

    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".", 1)[0]
                if top in internal:
                    _add(alias.name)
        elif isinstance(node, ast.ImportFrom) and (
            node.level > 0 or (node.module and node.module.split(".", 1)[0] in internal)
        ):
            base = node.module or ""
            for alias in node.names:
                label = f"{base}.{alias.name}" if base else alias.name
                _add(label)
    return seen


def _plain_block(rel: str, path: Path) -> str:
    try:
        loc = sum(1 for _ in path.open("rb"))
    except OSError:
        loc = 0
    return f"{rel} [{loc}L]"


def _top_level_symbols(tree: ast.Module, lines: list[str]) -> list[str]:
    out: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            class_line = f"class {node.name}"
            class_doc = _docstring_summary(node)
            if class_doc:
                class_line += f"  # {class_doc}"
            out.append(class_line)
            for m in node.body:
                if isinstance(m, ast.FunctionDef | ast.AsyncFunctionDef):
                    prefix = "async def " if isinstance(m, ast.AsyncFunctionDef) else "def "
                    sig = _func_signature(m, prefix=prefix)
                    doc = _docstring_summary(m)
                    line = f"  {sig}"
                    if doc:
                        line += f"  # {doc}"
                    out.append(line)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            prefix = "async def " if isinstance(node, ast.AsyncFunctionDef) else "def "
            sig = _func_signature(node, prefix=prefix)
            doc = _docstring_summary(node)
            if doc:
                sig += f"  # {doc}"
            out.append(sig)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    out.append(f"{target.id} = ...")
    return out


# Cap so a verbose docstring can't blow the map budget — first sentence is
# what the model needs to disambiguate similarly-named symbols.
_DOC_MAX_CHARS = 100


def _docstring_summary(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
) -> str:
    """Return the first sentence of the symbol's docstring (≤100 chars).

    The MAP otherwise only carries signatures — names alone can't tell the
    model what a method actually does. With a one-liner from the docstring,
    qwen-coder picks `StepAgent.compact (Summarize history…)` over
    `Session.mark_compacted (Snapshot for footer math…)` instead of just
    matching on the substring `compact`.
    """
    doc = ast.get_docstring(node)
    if not doc:
        return ""
    # First sentence: cut at the first period followed by space/newline, or
    # at the first newline if no period. Strip whitespace, collapse internal
    # whitespace to single spaces.
    first = doc.strip().split("\n", 1)[0].strip()
    if "." in first:
        first = first.split(".", 1)[0] + "."
    first = " ".join(first.split())
    if len(first) > _DOC_MAX_CHARS:
        first = first[: _DOC_MAX_CHARS - 1].rstrip() + "…"
    return first


def _func_signature(node: ast.FunctionDef | ast.AsyncFunctionDef, *, prefix: str) -> str:
    args: list[str] = []
    for a in node.args.args:
        if a.annotation is not None:
            args.append(f"{a.arg}: {ast.unparse(a.annotation)}")
        else:
            args.append(a.arg)
    sig = f"{prefix}{node.name}({', '.join(args)})"
    if node.returns is not None:
        sig += f" -> {ast.unparse(node.returns)}"
    return sig
