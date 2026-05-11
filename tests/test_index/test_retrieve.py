"""Tests for `code_scalpel.index.retrieve.search`.

Covers project-wide vs single-file walks, two-track scoring (name +2 /
docstring +1), tokenizer behaviour, top-k cap, and the empty / non-
Python guardrails.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from code_scalpel.index.retrieve import search


def test_search_finds_symbol_by_name(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def compact_context():\n    pass\n")
    hits = search(tmp_path, "compact")
    assert len(hits) == 1
    assert hits[0].qualified_name == "compact_context"
    assert hits[0].rel_path == "a.py"
    assert hits[0].kind == "function"


def test_name_match_outranks_docstring_match(tmp_path: Path) -> None:
    """Name hit is worth +2, docstring hit is worth +1 — so a symbol
    whose name contains the token must rank above one that only mentions
    it in the docstring."""
    (tmp_path / "a.py").write_text(
        textwrap.dedent('''\
            def compact():
                """Unrelated summary."""
                pass

            def helper():
                """Handles compact calls for the pipeline."""
                pass
            ''')
    )
    hits = search(tmp_path, "compact")
    assert [h.qualified_name for h in hits] == ["compact", "helper"]
    assert hits[0].score > hits[1].score


def test_path_scopes_search_to_one_file(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def needle(): pass\n")
    (tmp_path / "b.py").write_text("def needle(): pass\n")
    hits = search(tmp_path, "needle", path="a.py")
    assert {h.rel_path for h in hits} == {"a.py"}


def test_multi_token_query_rewards_multi_token_hits(tmp_path: Path) -> None:
    """`re.findall(r"\\w+")` on the query splits on whitespace AND
    punctuation. A symbol that hits BOTH tokens must outrank one that
    hits only one."""
    (tmp_path / "a.py").write_text(
        textwrap.dedent("""\
            def context_compress():
                pass

            def context_only():
                pass
            """)
    )
    hits = search(tmp_path, "context, compress")
    assert hits[0].qualified_name == "context_compress"
    assert hits[0].score > hits[1].score


def test_case_insensitive_matching(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("class HTTPClient:\n    pass\n")
    hits = search(tmp_path, "httpclient")
    assert len(hits) == 1
    assert hits[0].qualified_name == "HTTPClient"


def test_empty_query_returns_empty_tuple(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def foo(): pass\n")
    assert search(tmp_path, "") == ()
    # punctuation-only query also tokenises to nothing
    assert search(tmp_path, "  ?? !!  ") == ()


def test_empty_project_returns_empty_tuple(tmp_path: Path) -> None:
    assert search(tmp_path, "anything") == ()


def test_top_k_cap_respected(tmp_path: Path) -> None:
    body = "\n".join(f"def needle_{i}():\n    pass" for i in range(20))
    (tmp_path / "a.py").write_text(body + "\n")
    hits = search(tmp_path, "needle", k=3)
    assert len(hits) == 3


def test_non_python_files_dont_crash_walk(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# needle\nsome prose\n")
    (tmp_path / "data.json").write_text('{"k": "needle"}\n')
    (tmp_path / "a.py").write_text("def needle(): pass\n")
    hits = search(tmp_path, "needle")
    # Only the .py symbol is surfaced; .md / .json don't error and don't
    # leak as fake hits.
    assert len(hits) == 1
    assert hits[0].rel_path == "a.py"


def test_zero_score_rows_dropped(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text(
        textwrap.dedent("""\
            def needle():
                pass

            def unrelated():
                pass
            """)
    )
    hits = search(tmp_path, "needle")
    assert all(h.qualified_name == "needle" for h in hits)
    assert all(h.score > 0 for h in hits)


def test_tie_break_by_lineno_within_same_file(tmp_path: Path) -> None:
    """When two symbols score equally, the earlier line wins. Deterministic
    ordering matters for the LLM — same query, same result, every run."""
    (tmp_path / "a.py").write_text(
        textwrap.dedent("""\
            def needle_a():
                pass

            def needle_b():
                pass
            """)
    )
    hits = search(tmp_path, "needle")
    assert [h.qualified_name for h in hits] == ["needle_a", "needle_b"]
    assert hits[0].lineno < hits[1].lineno
