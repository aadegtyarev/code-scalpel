"""Static check: every `from X import Y` resolves to an actual export.

14b regularly writes `from project.module import Helper` where the
function is named `_helper` (private), or `helper` (lower-case), or
the module doesn't exist. The import statement looks plausible, the
file compiles, but `pytest` blows up on collection — which is a
slower and noisier failure than "we already know this won't resolve".

The check walks `from … import …` statements in the changed file
and, for each imported name from an in-project module, asks: does
that module exist on disk, and does it actually expose this name?
The answer comes from `importlib.util.find_spec` + a static AST
walk of the target module's top-level (no execution — that would
import side-effects).

Out of scope:
- Star imports (`from X import *`) — by definition.
- Third-party / stdlib imports — finding `requests.get` is what
  mypy is for; we'd duplicate type-checker work without its smarts.
- `import X.Y as Z` aliasing chains.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ImportIssue:
    """One unresolved import in one file."""

    file: Path
    line: int
    module: str
    name: str
    reason: str  # "module not found" | "name not exported"


def check_imports(path: Path | str, project_root: Path) -> list[ImportIssue]:
    """Walk `from … import …` in `path`; return any name that doesn't
    resolve in the project tree under `project_root`.

    Stdlib / site-packages imports are skipped — we only audit modules
    that live inside the project (their dotted name resolves to a
    file under `project_root`). Star imports are also skipped because
    enumerating the wildcard requires executing the module.
    """
    p = Path(path)
    if not p.is_file():
        return []
    try:
        source = p.read_text()
    except OSError:
        return []
    try:
        tree = ast.parse(source, filename=str(p))
    except SyntaxError:
        return []

    issues: list[ImportIssue] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.module is None or node.level:
            # Relative imports — out of scope for now; resolving them
            # cleanly needs the package context of `path`.
            continue
        target_file = _resolve_module(node.module, project_root)
        if target_file is None:
            continue  # external import — skip
        exports = _top_level_names(target_file)
        if exports is None:
            continue
        for alias in node.names:
            name = alias.name
            if name == "*":
                continue
            if name not in exports:
                issues.append(
                    ImportIssue(
                        file=p,
                        line=node.lineno,
                        module=node.module,
                        name=name,
                        reason="name not exported",
                    )
                )
    return issues


def _resolve_module(dotted: str, project_root: Path) -> Path | None:
    """Map `pkg.sub.mod` to `<project_root>/pkg/sub/mod.py` (or
    `__init__.py` if it's a package). Returns None for external
    modules (stdlib / site-packages).

    We resolve via the project filesystem rather than `importlib`
    because importing the target executes it — and many in-project
    modules touch the LLM / network / shell at import time, which
    we obviously don't want during a check."""
    parts = dotted.split(".")
    candidate_mod = project_root.joinpath(*parts).with_suffix(".py")
    if candidate_mod.is_file():
        return candidate_mod
    candidate_pkg = project_root.joinpath(*parts, "__init__.py")
    if candidate_pkg.is_file():
        return candidate_pkg
    return None


def _top_level_names(module_path: Path) -> set[str] | None:
    """Return the set of names a module exports at its top level —
    functions, classes, constants. Honours `__all__` if it's a plain
    list/tuple literal. None on parse failure (caller skips silently)."""
    try:
        source = module_path.read_text()
    except OSError:
        return None
    try:
        tree = ast.parse(source, filename=str(module_path))
    except SyntaxError:
        return None
    explicit = _read_dunder_all(tree)
    if explicit is not None:
        return explicit
    out: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            out.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            out.add(node.target.id)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    continue
                out.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                # `import x.y` exposes `x`; `import x as z` exposes `z`.
                out.add(alias.asname or alias.name.split(".")[0])
    return out


def _read_dunder_all(tree: ast.Module) -> set[str] | None:
    """If the module sets `__all__ = [...]` at the top level, return
    the names. Anything fancier (dynamic build, += extension) → fall
    back to the inferred set."""
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "__all__":
                value = node.value
                if isinstance(value, ast.List | ast.Tuple):
                    names: set[str] = set()
                    for elt in value.elts:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            names.add(elt.value)
                        else:
                            return None
                    return names
    return None


__all__ = ["ImportIssue", "check_imports"]
