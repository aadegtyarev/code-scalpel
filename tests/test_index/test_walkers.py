"""Tests for `code_scalpel.index.walkers.walk_python`."""

from __future__ import annotations

import textwrap

from code_scalpel.index.walkers import walk_python


def _walk(source: str, *, internal: frozenset[str] = frozenset()) -> tuple:
    return walk_python(source.encode("utf-8"), internal=internal)


def test_top_level_class_and_function() -> None:
    symbols, _ = _walk(
        textwrap.dedent("""\
            class Greeter:
                def hello(self, name):
                    return name

            def goodbye():
                return "bye"
            """)
    )
    kinds = [(s.kind, s.qualified_name) for s in symbols]
    assert ("class", "Greeter") in kinds
    assert ("method", "Greeter.hello") in kinds
    assert ("function", "goodbye") in kinds


def test_async_function_and_method_kinds() -> None:
    symbols, _ = _walk(
        textwrap.dedent("""\
            class Net:
                async def fetch(self, url):
                    return url

            async def top():
                return 1
            """)
    )
    by_qn = {s.qualified_name: s.kind for s in symbols}
    assert by_qn["Net"] == "class"
    assert by_qn["Net.fetch"] == "async method"
    assert by_qn["top"] == "async function"


def test_line_numbers_are_one_based_and_end_lineno_set() -> None:
    symbols, _ = _walk(
        textwrap.dedent("""\
            # leading comment
            def f():
                return 1
            """)
    )
    fn = next(s for s in symbols if s.name == "f")
    assert fn.lineno == 2
    assert fn.end_lineno == 3


def test_docstring_first_sentence_truncated() -> None:
    long = "a" * 200
    symbols, _ = _walk(
        textwrap.dedent(f'''\
            def f():
                """{long}"""
                pass

            def g():
                """First sentence. Second sentence."""
                pass

            def h():
                """First line.
                Second line."""
                pass

            def n():
                pass
            ''')
    )
    by = {s.name: s.docstring for s in symbols}
    assert len(by["f"]) <= 100
    assert by["f"].endswith("…")
    assert by["g"] == "First sentence."
    assert by["h"] == "First line."
    assert by["n"] == ""


def test_class_docstring_captured() -> None:
    symbols, _ = _walk(
        textwrap.dedent('''\
            class Foo:
                """Class doc. Extra."""
                def bar(self):
                    pass
            ''')
    )
    cls = next(s for s in symbols if s.name == "Foo")
    assert cls.docstring == "Class doc."


def test_imports_filtered_to_internal() -> None:
    _, imports = _walk(
        textwrap.dedent("""\
            import os
            import code_scalpel.config
            from typing import Any
            from code_scalpel.config import Config, Other as O
            from . import x
            from .relative import z
            """),
        internal=frozenset({"code_scalpel"}),
    )
    assert "code_scalpel.config" in imports
    assert "code_scalpel.config.Config" in imports
    # aliased: project_map records the source-side name, not the alias
    assert "code_scalpel.config.Other" in imports
    # relative imports surface bare
    assert "x" in imports
    assert "z" in imports
    # external imports skipped
    assert all("typing" not in i for i in imports)
    assert "os" not in imports


def test_no_imports_when_internal_empty() -> None:
    _, imports = _walk("import os\nfrom typing import Any\n")
    assert imports == ()


def test_imports_deduplicated_and_order_preserved() -> None:
    _, imports = _walk(
        textwrap.dedent("""\
            from code_scalpel.config import Config
            from code_scalpel.config import Config
            from code_scalpel.memory import MemoryStore
            """),
        internal=frozenset({"code_scalpel"}),
    )
    assert imports == (
        "code_scalpel.config.Config",
        "code_scalpel.memory.MemoryStore",
    )


def test_syntax_error_is_tolerated() -> None:
    # tree-sitter recovers; we want no exception, partial result OK
    symbols, imports = _walk("def foo(\n")
    assert isinstance(symbols, tuple)
    assert isinstance(imports, tuple)


def test_empty_source_returns_empty() -> None:
    symbols, imports = _walk("")
    assert symbols == ()
    assert imports == ()


def test_decorated_class_and_function_are_unwrapped() -> None:
    symbols, _ = _walk(
        textwrap.dedent('''\
            @dataclass(frozen=True)
            class Foo:
                """Foo doc."""
                @staticmethod
                def make():
                    pass

            @decorator
            def top():
                """Top doc."""
                pass

            @decorator
            async def atop():
                pass
            ''')
    )
    by_qn = {s.qualified_name: s for s in symbols}
    assert by_qn["Foo"].kind == "class"
    assert by_qn["Foo"].docstring == "Foo doc."
    assert by_qn["Foo.make"].kind == "method"
    assert by_qn["top"].kind == "function"
    assert by_qn["top"].docstring == "Top doc."
    assert by_qn["atop"].kind == "async function"
    # lineno should include the decorator line (the decorator IS the
    # symbol's span as far as the editor is concerned).
    assert by_qn["top"].lineno < by_qn["top"].end_lineno


def test_multi_import_on_one_line() -> None:
    _, imports = _walk(
        "import code_scalpel.config, code_scalpel.memory\n",
        internal=frozenset({"code_scalpel"}),
    )
    assert "code_scalpel.config" in imports
    assert "code_scalpel.memory" in imports
