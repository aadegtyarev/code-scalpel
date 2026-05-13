"""AST-based detector for trivially-passing tests.

A test is "empty" when its body would still pass against a stub —
no production-code call, no assertion on a non-literal value. This
is the same failure mode `prompts/test_sanity.md` catches via LLM,
but the AST version is deterministic and runs in milliseconds: we
can gate /go on it without burning tokens.

Cases caught (any function whose name starts with `test_`):
- body is only `pass`, `...`, or a docstring
- only `assert <literal>` (`assert True`, `assert 1`, `assert "x"`,
  `assert ()`, etc.) — literals never fail meaningfully
- no Call expressions at all (no production code exercised)

Cases NOT caught (still trip `test_sanity` if enabled):
- imports the module, calls a function, asserts only `is not None`
  on its return value — there's a Call AND an Assert, but the
  assert is weak. Behavioural judgement, not structural; that's
  what the LLM judge is for.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class EmptyTest:
    """One test function whose body looks trivially-passing.

    `name` is the function (top-level or method). `reason` is a
    short string the caller can put on a chat card or a CI message.
    """

    name: str
    reason: str


def detect_empty_tests(path: Path | str) -> list[EmptyTest]:
    """Return every empty test in the file.

    Returns an empty list when the file doesn't exist, isn't valid
    Python, or has no test_ functions — the caller treats those as
    "nothing to check" and moves on. Exceptions never escape; this
    check must never crash /go.
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

    out: list[EmptyTest] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if not node.name.startswith("test_"):
            continue
        reason = _classify_body(node.body)
        if reason is not None:
            out.append(EmptyTest(name=node.name, reason=reason))
    return out


def _classify_body(body: list[ast.stmt]) -> str | None:
    """Return a reason string when the body is trivial, None when
    it looks meaningful enough to leave alone.

    Tightening this is fine — false positives here are visible to
    the user and easy to redact. False negatives just route the
    test to the LLM judge anyway."""
    # Strip a leading docstring; doesn't count as behaviour.
    effective = list(body)
    if (
        effective
        and isinstance(effective[0], ast.Expr)
        and isinstance(effective[0].value, ast.Constant)
        and isinstance(effective[0].value.value, str)
    ):
        effective = effective[1:]

    if not effective:
        return "empty body (only docstring or nothing)"

    has_call = False
    for stmt in effective:
        for sub in ast.walk(stmt):
            if isinstance(sub, ast.Call):
                has_call = True
                break
        if has_call:
            break

    only_pass_or_ellipsis = all(
        isinstance(stmt, ast.Pass)
        or (
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Constant)
            and stmt.value.value is Ellipsis
        )
        for stmt in effective
    )
    if only_pass_or_ellipsis:
        return "body is only pass/..."

    # Asserts on bare literals — assert True, assert 1 == 1, etc.
    asserts = [stmt for stmt in effective if isinstance(stmt, ast.Assert)]
    other_stmts = [stmt for stmt in effective if not isinstance(stmt, ast.Assert)]
    if asserts and not other_stmts and all(_is_literal_assert(stmt) for stmt in asserts):
        return "only asserts on literal values"

    if not has_call:
        return "no production-code call in the test body"

    return None


def _is_literal_assert(stmt: ast.Assert) -> bool:
    """True iff this assert compares only constants / tuples of constants.

    `assert True` → True. `assert 1 == 1` → True. `assert x == 1`
    → False (x is a Name). `assert hello() == 'hi'` → False (Call).
    """
    return _is_literal_expr(stmt.test) and (stmt.msg is None or _is_literal_expr(stmt.msg))


def _is_literal_expr(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.Tuple | ast.List | ast.Set):
        return all(_is_literal_expr(el) for el in node.elts)
    if isinstance(node, ast.Compare):
        return _is_literal_expr(node.left) and all(_is_literal_expr(c) for c in node.comparators)
    if isinstance(node, ast.UnaryOp):
        return _is_literal_expr(node.operand)
    if isinstance(node, ast.BoolOp):
        return all(_is_literal_expr(v) for v in node.values)
    return False
