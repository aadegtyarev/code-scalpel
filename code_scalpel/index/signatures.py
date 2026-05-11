"""Render a function/method signature from a tree-sitter parse node.

Phase 3 cutover: project_map.py's `_func_signature` did this off `ast`,
now we do it off tree-sitter so `FileIndex.symbols` can carry a populated
`signature` field and project_map.py no longer needs to import ast.

Output contract matches the previous ast renderer exactly:
  * positional and positional-or-keyword args only — `*args`, `**kwargs`,
    and kwonly args (after a bare `*`) are dropped.
  * argument default values are dropped (`b: int = 5` → `b: int`).
  * type annotations and return annotations are kept verbatim, source-
    sliced (so `'list[int]' | None` stays exactly as written).

The drops aren't accidental — they're the agreed compactness contract.
The MAP exists to fit in the model's context, and defaults / *args /
**kwargs almost never disambiguate where a method lives. Tests in
test_project_map.py assert against the same shape.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tree_sitter import Node


def render_signature(fn_node: Node, source: bytes, *, prefix: str) -> str:
    """Render `prefix + name(args) [-> return]` from a `function_definition`.

    `prefix` is the caller's choice (`"def "` or `"async def "`). We don't
    auto-detect async here because the caller already classifies the symbol
    kind — keeping signature rendering decoupled from kind detection means
    we don't have to walk the node twice.
    """
    name = _field_text(fn_node, "name", source)
    params = _render_params(fn_node, source)
    sig = f"{prefix}{name}({params})"
    return_node = fn_node.child_by_field_name("return_type")
    if return_node is not None:
        sig += f" -> {_node_text(return_node, source)}"
    return sig


def _render_params(fn_node: Node, source: bytes) -> str:
    """Walk the `parameters` child and emit only the positional args, with
    annotations but without defaults.

    Tree-sitter param node types:
      * `identifier`              — bare arg (no annotation, no default)
      * `typed_parameter`         — `name: type`
      * `default_parameter`       — `name = default`  (no annotation)
      * `typed_default_parameter` — `name: type = default`
      * `list_splat_pattern`      — `*args`            (skipped)
      * `dictionary_splat_pattern`— `**kwargs`          (skipped)
      * `*`/keyword_separator     — bare `*` boundary   (skipped, stops? no:
                                    we keep parity with ast.args.args which
                                    drops kwonly entirely)

    The previous ast helper looked at `node.args.args` only — positional +
    positional-or-keyword. Everything else (vararg, kwarg, kwonly) was
    dropped. We match that by walking the params node and ignoring
    anything that isn't one of the four arg-with-name forms above.

    Once we hit a `*` separator or `list_splat_pattern`, all subsequent
    args are kwonly in ast's model — and `ast.args.args` would not have
    contained them. We mirror that by stopping at the splat boundary.
    """
    params_node = fn_node.child_by_field_name("parameters")
    if params_node is None:
        return ""
    out: list[str] = []
    for child in params_node.children:
        ctype = child.type
        if ctype in {"(", ")", ","}:
            continue
        if ctype in {"list_splat_pattern", "dictionary_splat_pattern"}:
            # Once we cross *args / **kwargs, every following name is kwonly
            # or kwarg — ast's `.args.args` wouldn't have included them.
            break
        if ctype == "*":  # bare `*` boundary for kwonly args
            break
        out.append(_param_text(child, source))
    return ", ".join(p for p in out if p)


def _param_text(node: Node, source: bytes) -> str:
    """Render a single parameter as `name` or `name: annotation`.

    For `default_parameter` (e.g. `x=5`) we emit just `x` — same as ast's
    `arg` rendering. For `typed_default_parameter` (`x: int = 5`) we emit
    `x: int`, again matching ast. Defaults are intentionally dropped.
    """
    ctype = node.type
    if ctype == "identifier":
        return _node_text(node, source)
    if ctype == "typed_parameter":
        # Children: identifier ':' type
        name_node = _first_child_of_type(node, "identifier")
        type_node = node.child_by_field_name("type")
        if type_node is None:
            # Fallback: tree-sitter may not always set the field
            type_node = _first_child_of_type(node, "type")
        if name_node is None or type_node is None:
            return _node_text(node, source)
        return f"{_node_text(name_node, source)}: {_node_text(type_node, source)}"
    if ctype == "default_parameter":
        name_node = node.child_by_field_name("name") or _first_child_of_type(node, "identifier")
        if name_node is None:
            return _node_text(node, source)
        return _node_text(name_node, source)
    if ctype == "typed_default_parameter":
        name_node = node.child_by_field_name("name") or _first_child_of_type(node, "identifier")
        type_node = node.child_by_field_name("type") or _first_child_of_type(node, "type")
        if name_node is None or type_node is None:
            return _node_text(node, source)
        return f"{_node_text(name_node, source)}: {_node_text(type_node, source)}"
    # Anything else (e.g. positional-only marker `/`) — drop.
    return ""


def _first_child_of_type(node: Node, type_name: str) -> Node | None:
    for ch in node.children:
        if ch.type == type_name:
            return ch
    return None


def _node_text(node: Node, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _field_text(node: Node, field: str, source: bytes) -> str:
    target = node.child_by_field_name(field)
    if target is None:
        return ""
    return _node_text(target, source)
