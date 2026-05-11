"""Tests for the SEARCH/REPLACE edit-block parser and applier."""

from __future__ import annotations

import textwrap
from pathlib import Path

from code_scalpel.patch.edit_block import Edit, apply_edits, extract_edits

# ── parsing ──────────────────────────────────────────────────────────────────


def test_extract_single_block() -> None:
    text = textwrap.dedent("""\
        Here's the change:

        hello.py
        ```python
        <<<<<<< SEARCH
        def hello():
            pass
        =======
        def hello():
            return "hi"
        >>>>>>> REPLACE
        ```
        """)
    edits = extract_edits(text)
    assert len(edits) == 1
    assert edits[0].path == "hello.py"
    assert edits[0].search == "def hello():\n    pass\n"
    assert edits[0].replace == 'def hello():\n    return "hi"\n'


def test_extract_multiple_blocks_same_file() -> None:
    text = textwrap.dedent("""\
        a.py
        ```python
        <<<<<<< SEARCH
        x = 1
        =======
        x = 11
        >>>>>>> REPLACE
        ```

        a.py
        ```python
        <<<<<<< SEARCH
        y = 2
        =======
        y = 22
        >>>>>>> REPLACE
        ```
        """)
    edits = extract_edits(text)
    assert len(edits) == 2
    assert all(e.path == "a.py" for e in edits)


def test_extract_new_file_block() -> None:
    text = textwrap.dedent("""\
        new.py
        ```python
        <<<<<<< SEARCH
        =======
        print("hi")
        >>>>>>> REPLACE
        ```
        """)
    edits = extract_edits(text)
    assert len(edits) == 1
    assert edits[0].search == ""
    assert edits[0].replace == 'print("hi")\n'


def test_extract_returns_empty_when_no_blocks() -> None:
    assert extract_edits("just some prose, no blocks") == []


def test_extract_inherits_path_for_consecutive_blocks() -> None:
    """qwen emits multiple blocks under one path header inside a fenced section.
    Subsequent blocks must inherit the previous block's path, not pick up the
    ``>>>>>>> REPLACE`` marker as a phantom filename."""
    text = textwrap.dedent("""\
        math_utils.py
        ```python
        <<<<<<< SEARCH
        def add(a, b):
            return a + b
        =======
        def add(a: int, b: int) -> int:
            return a + b
        >>>>>>> REPLACE

        <<<<<<< SEARCH
        def subtract(a, b):
            return a - b
        =======
        def subtract(a: int, b: int) -> int:
            return a - b
        >>>>>>> REPLACE
        ```
        """)
    edits = extract_edits(text)
    assert len(edits) == 2
    assert all(e.path == "math_utils.py" for e in edits)


# ── applying ─────────────────────────────────────────────────────────────────


def test_apply_perfect_match(tmp_path: Path) -> None:
    (tmp_path / "x.py").write_text("a = 1\nb = 2\n")
    edits = [Edit(path="x.py", search="a = 1\n", replace="a = 100\n")]
    ok, err = apply_edits(edits, tmp_path)
    assert ok, err
    assert (tmp_path / "x.py").read_text() == "a = 100\nb = 2\n"


def test_apply_creates_new_file(tmp_path: Path) -> None:
    edits = [Edit(path="new.py", search="", replace='print("hi")\n')]
    ok, err = apply_edits(edits, tmp_path)
    assert ok, err
    assert (tmp_path / "new.py").read_text() == 'print("hi")\n'


def test_apply_creates_new_file_in_subdir(tmp_path: Path) -> None:
    edits = [Edit(path="pkg/sub/new.py", search="", replace="x = 1\n")]
    ok, _ = apply_edits(edits, tmp_path)
    assert ok
    assert (tmp_path / "pkg" / "sub" / "new.py").read_text() == "x = 1\n"


def test_apply_handles_whitespace_outdent(tmp_path: Path) -> None:
    """Model emitted SEARCH outdented; aider's recovery should align it."""
    (tmp_path / "u.py").write_text("class User:\n    def name(self):\n        return self._name\n")
    # Model dropped the 4-space class indent
    edits = [
        Edit(
            path="u.py",
            search="def name(self):\n    return self._name\n",
            replace="def name(self):\n    return self._name.upper()\n",
        )
    ]
    ok, err = apply_edits(edits, tmp_path)
    assert ok, err
    out = (tmp_path / "u.py").read_text()
    assert "return self._name.upper()" in out
    # Make sure class structure preserved
    assert out.startswith("class User:\n")


def test_apply_fails_when_search_absent(tmp_path: Path) -> None:
    (tmp_path / "x.py").write_text("a = 1\n")
    edits = [Edit(path="x.py", search="totally unrelated\n", replace="x\n")]
    ok, err = apply_edits(edits, tmp_path)
    assert not ok
    assert "SEARCH block did not match" in err
    # No write
    assert (tmp_path / "x.py").read_text() == "a = 1\n"


def test_apply_is_atomic_on_failure(tmp_path: Path) -> None:
    """If any edit fails, no files get touched — first edit must not leak."""
    (tmp_path / "good.py").write_text("a = 1\n")
    (tmp_path / "bad.py").write_text("b = 2\n")
    edits = [
        Edit(path="good.py", search="a = 1\n", replace="a = 99\n"),
        Edit(path="bad.py", search="nope\n", replace="x\n"),
    ]
    ok, _ = apply_edits(edits, tmp_path)
    assert not ok
    assert (tmp_path / "good.py").read_text() == "a = 1\n"
    assert (tmp_path / "bad.py").read_text() == "b = 2\n"


def test_apply_empty_edits_returns_false(tmp_path: Path) -> None:
    ok, err = apply_edits([], tmp_path)
    assert not ok
    assert "no edits" in err


def test_apply_prepends_when_search_is_empty_and_file_exists(tmp_path: Path) -> None:
    """qwen emits empty SEARCH for 'add line at top'. Must prepend, not overwrite."""
    (tmp_path / "p.py").write_text("def foo():\n    pass\n")
    edits = [Edit(path="p.py", search="", replace="from x import y")]
    ok, err = apply_edits(edits, tmp_path)
    assert ok, err
    assert (tmp_path / "p.py").read_text() == "from x import y\ndef foo():\n    pass\n"


def test_apply_treats_whitespace_only_search_as_empty(tmp_path: Path) -> None:
    """When the regex captures a blank line as the SEARCH body (model put a
    bare \\n between SEARCH and =======), don't try to match — prepend it
    instead. Otherwise the lone \\n matches every newline in the source."""
    (tmp_path / "p.py").write_text("def foo():\n    pass\n")
    edits = [
        Edit(path="p.py", search="\n", replace="from x import y"),
        Edit(path="p.py", search="def foo():\n    pass\n", replace="def foo():\n    return 1\n"),
    ]
    ok, err = apply_edits(edits, tmp_path)
    assert ok, err
    assert (tmp_path / "p.py").read_text() == "from x import y\ndef foo():\n    return 1\n"


# ── blank-line tolerance ────────────────────────────────────────────────────


def test_apply_tolerates_collapsed_blank_lines(tmp_path: Path) -> None:
    """File has TWO blank lines between defs, model emits SEARCH with ONE.
    The structural intent is identical; apply should still match.

    Regression repro for 2026-05-11 rename_function failure."""
    src = "def compute(x):\n    return x * 2\n\n\nprint(compute(5))\n"
    (tmp_path / "calc.py").write_text(src)
    edits = [
        Edit(
            path="calc.py",
            # one blank line between content (model collapsed)
            search="def compute(x):\n    return x * 2\n\nprint(compute(5))\n",
            replace="def double(x):\n    return x * 2\n\nprint(double(5))\n",
        ),
    ]
    ok, err = apply_edits(edits, tmp_path)
    assert ok, err
    text = (tmp_path / "calc.py").read_text()
    assert "def double(x):" in text
    assert "print(double(5))" in text
    assert "def compute" not in text


def test_apply_tolerates_expanded_blank_lines(tmp_path: Path) -> None:
    """Inverse: file has ONE blank line, model emits SEARCH with TWO."""
    src = "def a():\n    pass\n\ndef b():\n    pass\n"
    (tmp_path / "x.py").write_text(src)
    edits = [
        Edit(
            path="x.py",
            # two blank lines (model added one)
            search="def a():\n    pass\n\n\ndef b():\n    pass\n",
            replace="def a():\n    return 1\n\ndef b():\n    return 2\n",
        ),
    ]
    ok, err = apply_edits(edits, tmp_path)
    assert ok, err


def test_apply_tolerates_indent_AND_blank_mismatch(tmp_path: Path) -> None:
    """The actual 2026-05-11 rename_function regression: model emits SEARCH
    with BOTH a uniform 4-space leading prefix (copied from the prompt
    example) AND a different blank-line count (1 instead of 2). Apply
    must dedent + blank-tolerate at the same time."""
    src = "def compute(x):\n    return x * 2\n\n\nprint(compute(5))\n"
    (tmp_path / "calc.py").write_text(src)
    edits = [
        Edit(
            path="calc.py",
            search=(
                "    def compute(x):\n"
                "        return x * 2\n"
                "\n"  # 1 blank vs file's 2
                "    print(compute(5))\n"
            ),
            replace=("    def double(x):\n        return x * 2\n\n    print(double(5))\n"),
        ),
    ]
    ok, err = apply_edits(edits, tmp_path)
    assert ok, err
    text = (tmp_path / "calc.py").read_text()
    assert "def double(x):" in text
    assert "print(double(5))" in text
    assert "def compute" not in text
