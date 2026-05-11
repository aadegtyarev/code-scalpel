"""Tests for the project map builder."""

from __future__ import annotations

import textwrap
from pathlib import Path

from code_scalpel.project_map import build_file_map, build_map, build_map_overview


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


def test_internal_imports_appear_in_block(tmp_path: Path) -> None:
    """Each file block carries an `imports:` line listing intra-project
    imports. This is what lets the model verify 'X uses Y' claims without
    grep — if Y isn't listed, X doesn't import it."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "core.py").write_text(
        textwrap.dedent("""\
            from pkg.helpers import helper_one
            from pkg.helpers import helper_two

            def main():
                pass
        """)
    )
    (tmp_path / "pkg" / "helpers.py").write_text("def helper_one(): pass\ndef helper_two(): pass\n")
    out = build_map(tmp_path, use_cache=False)
    line = next(ln for ln in out.splitlines() if ln.startswith("  imports:"))
    assert "pkg.helpers.helper_one" in line
    assert "pkg.helpers.helper_two" in line


def test_external_imports_filtered_out(tmp_path: Path) -> None:
    """typing / pathlib / pydantic noise out — they don't trace project flow.
    Only intra-project imports stay."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "x.py").write_text(
        textwrap.dedent("""\
            from typing import Any
            from pathlib import Path
            from pydantic import BaseModel
            from pkg.helpers import h
        """)
    )
    (tmp_path / "pkg" / "helpers.py").write_text("def h(): pass\n")
    out = build_map(tmp_path, use_cache=False)
    block_lines = [ln for ln in out.splitlines() if "pkg/x.py" in ln or ln.startswith("  imports:")]
    # The imports line directly after the pkg/x.py header
    imports_idx = next(i for i, ln in enumerate(out.splitlines()) if "pkg/x.py" in ln) + 1
    imports_line = out.splitlines()[imports_idx]
    assert "pkg.helpers.h" in imports_line
    assert "typing" not in imports_line
    assert "pathlib" not in imports_line
    assert "pydantic" not in imports_line
    del block_lines  # unused; kept for readability of intent


def test_no_imports_line_when_module_has_no_internal_imports(tmp_path: Path) -> None:
    """Clean output for modules that only use stdlib — no empty
    `imports: ` line trailing nothing."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "lone.py").write_text(
        textwrap.dedent("""\
            from typing import Any

            def f():
                pass
        """)
    )
    out = build_map(tmp_path, use_cache=False)
    # Find the lone.py block (between its header and the next file header)
    lines = out.splitlines()
    start = next(i for i, ln in enumerate(lines) if "pkg/lone.py" in ln)
    end = next(
        (i for i, ln in enumerate(lines[start + 1 :], start + 1) if not ln.startswith(" ")),
        len(lines),
    )
    block = "\n".join(lines[start:end])
    assert "imports:" not in block


def test_relative_imports_captured(tmp_path: Path) -> None:
    """`from . import foo` and `from .helpers import bar` are intra-project
    by definition — capture them regardless of the package-name heuristic."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "core.py").write_text("from .helpers import h\nfrom . import util\n")
    (tmp_path / "pkg" / "helpers.py").write_text("def h(): pass\n")
    (tmp_path / "pkg" / "util.py").write_text("X = 1\n")
    out = build_map(tmp_path, use_cache=False)
    imports_line = next(ln for ln in out.splitlines() if ln.startswith("  imports:"))
    assert "helpers.h" in imports_line
    assert "util" in imports_line


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


def test_overview_has_paths_but_no_symbols(tmp_path: Path) -> None:
    """The overview is paths + line counts only — symbols stay behind the
    `map_file` tool. Per-turn token budget shrinks ~10× this way."""
    (tmp_path / "a.py").write_text("class Foo:\n    def bar(self):\n        pass\n")
    (tmp_path / "b.py").write_text("def baz():\n    return 1\n")
    overview = build_map_overview(tmp_path)
    assert "a.py" in overview
    assert "b.py" in overview
    # No symbols — that's the whole point
    assert "class Foo" not in overview
    assert "def bar" not in overview
    assert "def baz" not in overview
    # Line counts are present
    assert "[3L]" in overview  # a.py
    assert "[2L]" in overview  # b.py


def test_overview_is_drastically_smaller_than_full_map(tmp_path: Path) -> None:
    """The whole point of the overview is to fit the per-turn context
    where the full symbol map would not."""
    body = "class C:\n" + "\n".join(f"    def m{i}(self): pass" for i in range(40)) + "\n"
    for name in "abcdefghij":
        (tmp_path / f"{name}.py").write_text(body)
    overview = build_map_overview(tmp_path)
    full = build_map(tmp_path, use_cache=False)
    # Overview should be at least 5× smaller — usually 10-15× on real code
    assert len(overview) * 5 < len(full)


def test_overview_skips_directories(tmp_path: Path) -> None:
    """list_files already filters to files, but make sure the overview
    builder doesn't try to count lines on a directory."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text("x = 1\n")
    overview = build_map_overview(tmp_path)
    assert "pkg/mod.py" in overview
    # Directory itself should never show up as an entry
    for line in overview.splitlines():
        assert line != "pkg [0L]"


def test_file_map_returns_full_block_for_python(tmp_path: Path) -> None:
    """`build_file_map` is the drilldown: same block format the bigger
    map would produce, but for ONE file."""
    (tmp_path / "x.py").write_text(
        textwrap.dedent("""\
            \"\"\"Module that does things.\"\"\"

            from code_scalpel.foo import bar

            class Greeter:
                \"\"\"Greets the user.\"\"\"

                def hello(self, name: str) -> str:
                    return f"Hi {name}"
            """)
    )
    # Make `code_scalpel` look internal so its imports appear
    (tmp_path / "code_scalpel").mkdir()
    (tmp_path / "code_scalpel" / "__init__.py").write_text("")
    block = build_file_map(tmp_path, "x.py")
    assert "x.py" in block
    assert "class Greeter" in block
    assert "def hello(self, name: str) -> str" in block
    assert "Greets the user" in block
    # Imports surfaced when internal
    assert "code_scalpel.foo.bar" in block


def test_file_map_handles_non_python(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# title\n\nbody\n")
    block = build_file_map(tmp_path, "README.md")
    assert "README.md" in block
    assert "[3L]" in block


def test_file_map_missing_file(tmp_path: Path) -> None:
    block = build_file_map(tmp_path, "nope.py")
    assert "not found" in block


def test_file_map_handles_syntax_error(tmp_path: Path) -> None:
    """Half-typed files shouldn't kill the drilldown — fall back to the
    line-count header so the model still gets *something* back."""
    (tmp_path / "broken.py").write_text("def f(:\n    pass\n")
    block = build_file_map(tmp_path, "broken.py")
    assert "broken.py" in block
    assert "parse error" in block
