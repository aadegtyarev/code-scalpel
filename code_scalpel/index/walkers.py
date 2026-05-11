"""Tree-sitter walker for Python: emit `Symbol`s + filtered imports.

Mirrors what `project_map._top_level_symbols` + `_internal_imports` do but
over a tree-sitter parse tree. Async functions/methods are flagged via the
leading `async` keyword child (tree-sitter-python folds them into the same
`function_definition` node, unlike `ast`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from code_scalpel.index.model import Symbol
from code_scalpel.index.parser import python_parser

if TYPE_CHECKING:
    from tree_sitter import Node


_DOC_MAX_CHARS = 100


def walk_python(
    source: bytes,
    *,
    internal: frozenset[str] = frozenset(),
) -> tuple[tuple[Symbol, ...], tuple[str, ...]]:
    """Parse `source` and return (top-level symbols, internal imports).

    Tree-sitter has built-in error recovery: malformed input yields a partial
    tree rather than an exception, so we don't try/except here. A file that
    won't parse at all just produces an empty tuple — same observable shape
    as a file with no symbols.
    """
    tree = python_parser().parse(source)
    root = tree.root_node
    symbols = tuple(_top_level_symbols(root, source))
    imports = tuple(_internal_imports(root, source, internal))
    return symbols, imports


def _top_level_symbols(root: Node, source: bytes) -> list[Symbol]:
    out: list[Symbol] = []
    for raw_child in root.children:
        child = _unwrap_decorated(raw_child)
        if child.type == "class_definition":
            cls_name = _name_text(child, source)
            if not cls_name:
                continue
            out.append(
                Symbol(
                    name=cls_name,
                    kind="class",
                    qualified_name=cls_name,
                    lineno=raw_child.start_point[0] + 1,
                    end_lineno=raw_child.end_point[0] + 1,
                    docstring=_docstring_for(child, source),
                )
            )
            out.extend(_class_methods(child, source, cls_name))
        elif child.type == "function_definition":
            fn_name = _name_text(child, source)
            if not fn_name:
                continue
            out.append(
                Symbol(
                    name=fn_name,
                    kind="async_function" if _is_async(child) else "function",
                    qualified_name=fn_name,
                    lineno=raw_child.start_point[0] + 1,
                    end_lineno=raw_child.end_point[0] + 1,
                    docstring=_docstring_for(child, source),
                )
            )
    return out


def _class_methods(class_node: Node, source: bytes, class_name: str) -> list[Symbol]:
    body = class_node.child_by_field_name("body")
    if body is None:
        return []
    out: list[Symbol] = []
    for raw_m in body.children:
        m = _unwrap_decorated(raw_m)
        if m.type != "function_definition":
            continue
        m_name = _name_text(m, source)
        if not m_name:
            continue
        out.append(
            Symbol(
                name=m_name,
                kind="async_method" if _is_async(m) else "method",
                qualified_name=f"{class_name}.{m_name}",
                lineno=raw_m.start_point[0] + 1,
                end_lineno=raw_m.end_point[0] + 1,
                docstring=_docstring_for(m, source),
            )
        )
    return out


def _unwrap_decorated(node: Node) -> Node:
    """Return the underlying class/function node, peeling off decorators.

    Tree-sitter-python wraps `@dec` + `def f` into a `decorated_definition`
    that carries the decorator nodes plus the real definition. We want the
    inner one for kind/name/body lookups; the outer one's span (which
    includes the decorators) is preserved separately for lineno reporting.
    """
    if node.type != "decorated_definition":
        return node
    for ch in node.children:
        if ch.type in {"class_definition", "function_definition"}:
            return ch
    return node


def _is_async(fn_node: Node) -> bool:
    return any(c.type == "async" for c in fn_node.children)


def _name_text(node: Node, source: bytes) -> str:
    name_node = node.child_by_field_name("name")
    if name_node is None:
        return ""
    return source[name_node.start_byte : name_node.end_byte].decode("utf-8", errors="replace")


def _docstring_for(node: Node, source: bytes) -> str:
    """First-sentence summary of the symbol's docstring, capped at 100 chars.

    Matches `project_map._docstring_summary`: split at the first newline, then
    cut at the first period if any, collapse whitespace, ellipsise if long.
    """
    body = node.child_by_field_name("body")
    if body is None or not body.children:
        return ""
    first = body.children[0]
    if first.type != "expression_statement" or not first.children:
        return ""
    inner = first.children[0]
    if inner.type != "string":
        return ""
    raw = _string_content(inner, source)
    if not raw:
        return ""
    line = raw.strip().split("\n", 1)[0].strip()
    if "." in line:
        line = line.split(".", 1)[0] + "."
    line = " ".join(line.split())
    if len(line) > _DOC_MAX_CHARS:
        line = line[: _DOC_MAX_CHARS - 1].rstrip() + "…"
    return line


def _string_content(string_node: Node, source: bytes) -> str:
    """Pull text out of a tree-sitter `string` node, skipping the quote tokens.

    The node decomposes into `string_start` + (one or more `string_content`)
    + `string_end`; we concatenate the contents so f-strings or multi-piece
    literals (rare in docstrings, but possible) still come through.
    """
    parts: list[str] = []
    for child in string_node.children:
        if child.type == "string_content":
            parts.append(
                source[child.start_byte : child.end_byte].decode("utf-8", errors="replace")
            )
    if parts:
        return "".join(parts)
    # Fallback for older grammars that don't split string_content out: strip
    # quotes by hand. Tree-sitter-python ≥0.23 emits string_content, so this
    # path is just defensive.
    text = source[string_node.start_byte : string_node.end_byte].decode("utf-8", errors="replace")
    return text.strip("\"'")


def _internal_imports(root: Node, source: bytes, internal: frozenset[str]) -> list[str]:
    """Top-level imports whose first dotted segment is in `internal`.

    Format mirrors project_map: `from foo.bar import Baz` → `"foo.bar.Baz"`,
    `import foo.bar` → `"foo.bar"`. Relative imports (`from . import x`) are
    surfaced as bare `"x"` — matches project_map's behaviour even though we
    can't resolve them to absolute names here.
    """
    seen: list[str] = []

    def _add(label: str) -> None:
        if label and label not in seen:
            seen.append(label)

    for node in root.children:
        if node.type == "import_statement":
            for name_node in _named_children(node, "name"):
                full = _dotted_text(name_node, source)
                if not full:
                    continue
                top = full.split(".", 1)[0]
                if top in internal:
                    _add(full)
        elif node.type == "import_from_statement":
            module_node = node.child_by_field_name("module_name")
            is_relative = module_node is not None and module_node.type == "relative_import"
            base = _dotted_text(module_node, source) if module_node is not None else ""
            base_top = base.split(".", 1)[0] if base else ""
            if not is_relative and base_top not in internal:
                continue
            for name_node in _named_children(node, "name"):
                alias = _import_target_name(name_node, source)
                if not alias:
                    continue
                if is_relative:
                    _add(alias)
                else:
                    _add(f"{base}.{alias}" if base else alias)
    return seen


def _named_children(node: Node, field: str) -> list[Node]:
    """Return every child of `node` whose field name is `field`.

    `child_by_field_name` only returns the first match, but import statements
    can have multiple `name` fields (`import a, b`). The cursor API gives us
    per-child field lookups.
    """
    out: list[Node] = []
    cursor = node.walk()
    if not cursor.goto_first_child():
        return out
    while True:
        if cursor.field_name == field and cursor.node is not None:
            out.append(cursor.node)
        if not cursor.goto_next_sibling():
            break
    return out


def _dotted_text(node: Node | None, source: bytes) -> str:
    if node is None:
        return ""
    if node.type == "relative_import":
        return ""
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _import_target_name(node: Node, source: bytes) -> str:
    """Resolve the imported symbol's name in source-position order.

    `aliased_import` carries the original name in the `name` field; we use
    that (not the alias) because project_map does the same — what matters
    for flow analysis is which symbol the project depends on.
    """
    if node.type == "aliased_import":
        target = node.child_by_field_name("name")
        if target is None:
            return ""
        return source[target.start_byte : target.end_byte].decode("utf-8", errors="replace")
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")
