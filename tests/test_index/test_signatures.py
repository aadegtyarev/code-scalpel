"""Tests for `code_scalpel.index.signatures.render_signature`.

The output contract matches what `project_map._func_signature` used to do
off `ast`: positional args only (no varargs, kwonly, kwargs), annotations
verbatim, defaults dropped. Test_project_map already pins down the
end-to-end shape — these tests pin the unit so we can ship grammar
upgrades or refactor the params walk without quietly regressing.
"""

from __future__ import annotations

from code_scalpel.index.parser import python_parser
from code_scalpel.index.signatures import render_signature


def _render(source: str, *, prefix: str = "def ") -> str:
    """Parse `source` (must contain exactly one top-level function) and
    render its signature."""
    src = source.encode("utf-8")
    tree = python_parser().parse(src)
    fn = next(c for c in tree.root_node.children if c.type == "function_definition")
    return render_signature(fn, src, prefix=prefix)


def test_bare_args_no_annotations() -> None:
    assert _render("def f(a, b, c): pass") == "def f(a, b, c)"


def test_args_with_type_hints() -> None:
    assert _render("def f(a: int, b: str) -> bool: pass") == "def f(a: int, b: str) -> bool"


def test_return_annotation_alone() -> None:
    """Return type without arg annotations — both halves render."""
    assert _render("def f(a) -> int: pass") == "def f(a) -> int"


def test_defaults_dropped_from_render() -> None:
    """`b: int = 5` collapses to `b: int`; `c=10` collapses to `c`."""
    assert _render("def f(a, b: int = 5, c=10) -> int: pass") == "def f(a, b: int, c) -> int"


def test_async_prefix_passes_through() -> None:
    """Caller picks the prefix — the renderer doesn't peek at the async
    keyword. Mirrors how the walker drives it based on kind."""
    assert (
        _render("async def fetch(url: str) -> str: pass", prefix="async def ")
        == "async def fetch(url: str) -> str"
    )


def test_varargs_and_kwargs_are_dropped() -> None:
    """`*args` / `**kwargs` get dropped — matches the ast helper that
    only looked at `node.args.args`. Everything after the splat boundary
    is kwonly anyway and would have been dropped too."""
    assert _render("def f(a, b, *args, c=1, **kwargs) -> int: pass") == "def f(a, b) -> int"


def test_complex_annotation_preserved_verbatim() -> None:
    """Quoted annotations, union types, generics — all source-sliced so
    they come out exactly as written. Mirrors `ast.unparse(annotation)`."""
    src = "def f(x: 'list[int]' | None, y: dict[str, int]) -> dict[str, int]: pass"
    assert _render(src) == "def f(x: 'list[int]' | None, y: dict[str, int]) -> dict[str, int]"
