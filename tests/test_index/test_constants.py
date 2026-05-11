"""Tests for `code_scalpel.index.walkers.walk_top_level_constants`.

The constant walker feeds the project map's `NAME = ...` lines. It must
keep the same filter rules the old ast helper enforced (uppercase only,
top-level only) plus the Phase 3 tightening (drop private `_FOO`).
"""

from __future__ import annotations

import textwrap

from code_scalpel.index.walkers import walk_top_level_constants


def _consts(source: str) -> list[str]:
    return [c.name for c in walk_top_level_constants(source.encode("utf-8"))]


def test_uppercase_constants_listed() -> None:
    src = "API_URL = 'x'\nMAX_RETRIES = 3\n"
    assert _consts(src) == ["API_URL", "MAX_RETRIES"]


def test_lowercase_names_skipped() -> None:
    """Lowercase names are regular variables, not constants — they
    pollute the MAP without disambiguating anything."""
    src = "lower = 1\nmixed_Case = 2\nUPPER = 3\n"
    assert _consts(src) == ["UPPER"]


def test_class_internal_constants_skipped() -> None:
    """`class C: BAR = 1` is class-level config, not a module constant.
    The MAP surfaces module-level UPPER names only — matches the old ast
    helper which iterated `tree.body`."""
    src = textwrap.dedent("""\
        TOP = 1

        class Cfg:
            BAR = 2
            BAZ = 3

        OTHER = 4
        """)
    assert _consts(src) == ["TOP", "OTHER"]


def test_leading_underscore_skipped() -> None:
    """`_PRIV` is a private-by-convention name. Phase 3 drops it from the
    MAP — even though `'_PRIV'.isupper()` is True, the underscore signals
    "internal", which is noise for the agent's flow-tracing context."""
    src = "PUBLIC = 1\n_PRIV = 2\n__DOUBLE = 3\n"
    assert _consts(src) == ["PUBLIC"]
