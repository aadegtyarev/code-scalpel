from __future__ import annotations

from code_scalpel.context_compress import compress_tool_message, should_compress


def test_should_compress_happy_path() -> None:
    """Age above threshold AND length above min — fire."""
    content = "x" * 1000
    assert should_compress(content, age_turns=5, threshold_turns=3, min_chars=800)


def test_should_compress_below_min_chars_short_circuit() -> None:
    """A short payload is its own summary — leave it alone regardless of age."""
    content = "0 failed, 12 passed"
    assert not should_compress(content, age_turns=10, threshold_turns=3, min_chars=800)


def test_should_compress_recent_message_short_circuit() -> None:
    """Within the threshold window the model still needs the raw output."""
    content = "x" * 5000
    assert not should_compress(content, age_turns=2, threshold_turns=3, min_chars=800)


def test_should_compress_idempotent_on_already_compressed() -> None:
    """A second pass over history must not wrap markers in markers."""
    marker = "[compressed: read_file(path=foo.py) → 0 lines / 0 chars, see turn 0]"
    assert not should_compress(marker, age_turns=10, threshold_turns=3, min_chars=10)


def test_compress_tool_message_includes_stats_and_first_line() -> None:
    """The marker carries tool/args/turn, the original line+char counts,
    and the first non-empty line as a hint."""
    content = "src/foo.py\n---\n1  def f():\n2      pass\n"
    out = compress_tool_message(
        content, tool_name="read_file", args_summary="path=src/foo.py", turn=1
    )
    assert "read_file(path=src/foo.py)" in out
    assert "see turn 1" in out
    # Stats reference the ORIGINAL content, not the marker.
    assert f"{content.count(chr(10))} lines" in out
    assert f"{len(content)} chars" in out
    # First non-empty line preserved as a hint.
    assert "src/foo.py" in out


def test_compress_tool_message_skips_hint_segment_when_blank() -> None:
    """Content with only whitespace produces a marker without the dangling
    `| ` hint separator — we don't want trailing punctuation that looks
    like a truncation bug to a human reader."""
    out = compress_tool_message("\n\n\n", tool_name="run_tests", args_summary="", turn=0)
    assert "run_tests()" in out
    assert "|" not in out


def test_compress_tool_message_truncates_long_first_line() -> None:
    """A pytest banner with a 500-char first line would re-bloat the very
    marker that's supposed to drop tokens. Hint gets truncated with an
    ellipsis suffix."""
    long_first = "FAILED " * 200
    content = long_first + "\nsecond line\n"
    out = compress_tool_message(content, tool_name="run_tests", args_summary="", turn=2)
    # Truncated to roughly _HINT_MAX_CHARS with an ellipsis.
    assert "…" in out
    # The full long first line did NOT make it through verbatim.
    assert long_first.strip() not in out


def test_compress_tool_message_no_lines_in_content() -> None:
    """Single-line content (no trailing newline) still has a line count
    of 1 — count the line, not the separators."""
    out = compress_tool_message(
        "only one line", tool_name="grep", args_summary="pattern=foo", turn=0
    )
    assert "1 lines" in out
    assert "only one line" in out
