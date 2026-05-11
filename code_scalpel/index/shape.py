"""Control-flow shape counts for a Python source — project-wide totals.

The agent uses these to decide whether a function is "risky" to edit: lots
of try/raise → exception-sensitive; nested loops → perf-sensitive; long
if-chains → branchy logic. Phase 1 just emits whole-file totals; per-symbol
counts come in Phase 3 (see plan).
"""

from __future__ import annotations

from code_scalpel.index.parser import python_parser

# Tree-sitter node types we count. `for_statement`, `while_statement`, and
# `list_comprehension` all roll up into one "loops" key so consumers don't
# have to know which sugar Python used.
_LOOPS = frozenset({"for_statement", "while_statement", "list_comprehension"})
_KEYS = ("try", "loops", "if", "raise")


def control_flow_shape(source: bytes) -> dict[str, int]:
    """Return shallow project-wide counts for `try`, `loops`, `if`, `raise`.

    Counts are recursive across the whole tree (so a `raise` inside an
    `except` clause is counted once). Empty/malformed input returns zeros
    — tree-sitter's error recovery means we still get a partial tree to
    walk.
    """
    counts: dict[str, int] = dict.fromkeys(_KEYS, 0)
    tree = python_parser().parse(source)
    cursor = tree.walk()

    def visit() -> None:
        node = cursor.node
        if node is None:
            return
        node_type = node.type
        if node_type == "try_statement":
            counts["try"] += 1
        elif node_type in _LOOPS:
            counts["loops"] += 1
        elif node_type == "if_statement":
            counts["if"] += 1
        elif node_type == "raise_statement":
            counts["raise"] += 1
        if cursor.goto_first_child():
            visit()
            while cursor.goto_next_sibling():
                visit()
            cursor.goto_parent()

    visit()
    return counts
