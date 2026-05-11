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
from pathlib import Path

from code_scalpel.tools.files import list_files

_INDEX_FILE = Path(".code-scalpel") / "INDEX.json"


def build_map(root: Path, max_files: int = 200, use_cache: bool = True) -> str:
    """Return a compact textual map of the project rooted at `root`.

    With `use_cache=True`, persists per-file blocks keyed by mtime so unchanged
    files don't get re-parsed on every turn. Massive win on larger projects.
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
                try:
                    source = path.read_text(errors="replace")
                except OSError:
                    continue
                block = _python_block(rel_key, source)
            else:
                block = _plain_block(rel_key, path)
        new_cache[rel_key] = {"mtime": mtime, "block": block}
        blocks.append(block)
    if use_cache:
        _save_cache(root, new_cache)
    return "\n".join(blocks)


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


def _python_block(rel: str, source: str) -> str:
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
    if not symbols:
        return header
    body = "\n".join(f"  {s}" for s in symbols)
    return f"{header}\n{body}"


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
            out.append(f"class {node.name}")
            for m in node.body:
                if isinstance(m, ast.FunctionDef | ast.AsyncFunctionDef):
                    out.append(
                        f"  {_func_signature(m, prefix='async def ' if isinstance(m, ast.AsyncFunctionDef) else 'def ')}"
                    )
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            prefix = "async def " if isinstance(node, ast.AsyncFunctionDef) else "def "
            out.append(_func_signature(node, prefix=prefix))
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    out.append(f"{target.id} = ...")
    return out


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
