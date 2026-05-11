"""Tests for the project map builder."""

from __future__ import annotations

import textwrap
from pathlib import Path

from code_scalpel.project_map import build_map


def test_python_file_shows_classes_and_functions(tmp_path: Path) -> None:
    (tmp_path / "foo.py").write_text(
        textwrap.dedent("""\
            class Greeter:
                def hello(self, name):
                    return f"Hi {name}"

            def goodbye():
                return "bye"
            """)
    )
    out = build_map(tmp_path)
    assert "foo.py" in out
    assert "class Greeter" in out
    assert "def hello(self, name)" in out
    assert "def goodbye()" in out


def test_function_signature_includes_annotations(tmp_path: Path) -> None:
    (tmp_path / "x.py").write_text("def add(a: int, b: int) -> int:\n    return a + b\n")
    out = build_map(tmp_path)
    assert "def add(a: int, b: int) -> int" in out


def test_async_function_marked_as_async(tmp_path: Path) -> None:
    (tmp_path / "x.py").write_text("async def fetch(url):\n    pass\n")
    out = build_map(tmp_path)
    assert "async def fetch(url)" in out


def test_top_level_constants_are_listed(tmp_path: Path) -> None:
    (tmp_path / "x.py").write_text("API_URL = 'https://...'\n_internal = 1\n")
    out = build_map(tmp_path)
    assert "API_URL = ..." in out
    # lowercase / underscore-prefix names are not surfaced — too noisy
    assert "_internal" not in out


def test_file_with_syntax_error_still_appears(tmp_path: Path) -> None:
    (tmp_path / "broken.py").write_text("def foo(\n")
    out = build_map(tmp_path)
    assert "broken.py" in out
    assert "parse error" in out


def test_non_python_file_shows_path_and_loc(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("hello\nworld\n")
    out = build_map(tmp_path)
    assert "README.md" in out
    assert "2L" in out


def test_subdirectory_files_appear(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "deep.py").write_text("def f():\n    pass\n")
    out = build_map(tmp_path)
    assert "pkg/deep.py" in out


def test_empty_python_file_shows_header_only(tmp_path: Path) -> None:
    (tmp_path / "empty.py").write_text("")
    out = build_map(tmp_path)
    assert "empty.py [0L]" in out


def test_map_caches_unchanged_files(tmp_path: Path) -> None:
    """Cached blocks should be reused when mtime hasn't changed."""
    import json

    (tmp_path / "x.py").write_text("def f():\n    pass\n")
    build_map(tmp_path)
    cache_path = tmp_path / ".code-scalpel" / "INDEX.json"
    assert cache_path.is_file()
    cache = json.loads(cache_path.read_text())
    assert "x.py" in cache

    # Corrupt the cached block — if cache is actually being used, we'll see the
    # corruption echoed back instead of a fresh parse.
    cache["x.py"]["block"] = "MARKER_FROM_CACHE"
    cache_path.write_text(json.dumps(cache))
    second = build_map(tmp_path)
    assert "MARKER_FROM_CACHE" in second


def test_map_invalidates_cache_when_mtime_changes(tmp_path: Path) -> None:
    import json
    import os
    import time

    (tmp_path / "x.py").write_text("def f():\n    pass\n")
    build_map(tmp_path)

    # Poison the cache then bump the file's mtime
    cache_path = tmp_path / ".code-scalpel" / "INDEX.json"
    cache = json.loads(cache_path.read_text())
    cache["x.py"]["block"] = "STALE"
    cache_path.write_text(json.dumps(cache))
    time.sleep(0.01)
    new_mtime = time.time()
    os.utime(tmp_path / "x.py", (new_mtime, new_mtime))

    refreshed = build_map(tmp_path)
    assert "STALE" not in refreshed
    assert "def f()" in refreshed


def test_docstrings_render_first_sentence_as_comment(tmp_path: Path) -> None:
    """The MAP must carry first-sentence docstrings so the model can
    disambiguate similar-named symbols (e.g. mark_compacted vs compact)
    without reading every file. Regression repro for 2026-05-11 bug."""
    (tmp_path / "x.py").write_text(
        textwrap.dedent('''\
            class Session:
                def mark_compacted(self) -> None:
                    """Anchor the footer budget to post-compact state."""
                    pass

            class Agent:
                async def compact(self) -> str | None:
                    """Summarize history into a short note and replace it."""
                    pass
        ''')
    )
    out = build_map(tmp_path, use_cache=False)
    assert "mark_compacted(self) -> None  # Anchor the footer budget" in out
    assert "compact(self) -> str | None  # Summarize history into a short note" in out


def test_no_docstring_means_no_comment_suffix(tmp_path: Path) -> None:
    """Symbols without docstrings stay clean — no trailing `# ` placeholder."""
    (tmp_path / "x.py").write_text("def bare(x: int) -> int:\n    return x\n")
    out = build_map(tmp_path, use_cache=False)
    assert "def bare(x: int) -> int" in out
    # No trailing comment marker glued to the signature
    assert "def bare(x: int) -> int  #" not in out


def test_docstring_truncated_at_100_chars(tmp_path: Path) -> None:
    """Long docstrings can't blow the map budget — capped at ~100 chars,
    suffixed with ellipsis when cut."""
    long_doc = "A " + "very " * 50 + "long single-sentence docstring without periods"
    (tmp_path / "x.py").write_text(f'def f(): """{long_doc}"""\n')
    out = build_map(tmp_path, use_cache=False)
    # Find the docstring fragment on the f() line
    line = next(ln for ln in out.splitlines() if "def f(" in ln)
    comment = line.split("#", 1)[1].strip() if "#" in line else ""
    assert comment.endswith("…")
    # Cap is ~100 chars total
    assert len(comment) <= 110


def test_class_docstring_also_carried(tmp_path: Path) -> None:
    (tmp_path / "x.py").write_text(
        textwrap.dedent('''\
            class Widget:
                """Inline TUI primitive."""
                pass
        ''')
    )
    out = build_map(tmp_path, use_cache=False)
    assert "class Widget  # Inline TUI primitive." in out


def test_multiline_docstring_uses_first_line(tmp_path: Path) -> None:
    (tmp_path / "x.py").write_text(
        textwrap.dedent('''\
            def f():
                """Short summary line.

                Longer explanation here that should NOT appear in the map.
                """
                pass
        ''')
    )
    out = build_map(tmp_path, use_cache=False)
    line = next(ln for ln in out.splitlines() if "def f(" in ln)
    assert "Short summary line." in line
    assert "Longer explanation" not in line


def test_map_is_substantially_smaller_than_full_content(tmp_path: Path) -> None:
    """The whole point of the map is token efficiency."""
    big = (
        textwrap.dedent("""\
        \"\"\"Module docstring that goes on and on...\"\"\"

        from typing import Any

        CONSTANT = 42

        class Big:
            def method_a(self, x: int) -> int:
                # 20 lines of body
                y = x * 2
                z = y + 1
                # ... imagine more lines here
                return z

            def method_b(self, s: str) -> str:
                return s.upper()
            """)
        * 5
    )  # repeat to make it longer

    (tmp_path / "big.py").write_text(big)
    out = build_map(tmp_path)
    assert len(out) < len(big) // 2
