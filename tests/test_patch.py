from __future__ import annotations

from pathlib import Path

import pytest

from code_scalpel.patch.applier import apply_patch, rollback
from code_scalpel.patch.normalizer import fix_hunk_headers
from code_scalpel.patch.parser import extract_patch, parse_patch
from code_scalpel.patch.validator import validate_patch
from code_scalpel.tools.shell import ShellResult
from code_scalpel.tools.tests import RunResult, _parse, run_tests
from tests.mocks import MockShellRunner

VALID_PATCH = """\
diff --git a/hello.py b/hello.py
index 1234567..abcdefg 100644
--- a/hello.py
+++ b/hello.py
@@ -1,2 +1,2 @@
 def hello():
-    pass
+    return "hi"
"""


# --- normalizer ---


def test_fix_hunk_headers_corrects_undercount() -> None:
    """LLM forgot blank context line — @@ -1,2 should be @@ -1,3."""
    patch = (
        "--- a/f.py\n+++ b/f.py\n"
        "@@ -1,2 +1,2 @@\n"
        "-def add(a, b):\n"
        "+def add(a: int, b: int) -> int:\n"
        "     return a + b\n"
        " \n"
    )
    fixed = fix_hunk_headers(patch)
    assert "@@ -1,3 +1,3 @@" in fixed


def test_fix_hunk_headers_leaves_correct_untouched() -> None:
    patch = "--- a/f.py\n+++ b/f.py\n@@ -1,2 +1,2 @@\n def hello():\n-    pass\n+    return 1\n"
    fixed = fix_hunk_headers(patch)
    assert "@@ -1,2 +1,2 @@" in fixed


def test_extract_normalizes_bad_hunk_count() -> None:
    """extract_patch must accept and fix LLM diffs with wrong hunk counts."""
    bad = (
        "```diff\n"
        "--- a/f.py\n+++ b/f.py\n"
        "@@ -1,2 +1,2 @@\n"
        "-def add(a, b):\n"
        "+def add(a: int, b: int) -> int:\n"
        "     return a + b\n"
        " \n"
        "```"
    )
    result = extract_patch(bad)
    assert result is not None
    assert "@@ -1,3 +1,3 @@" in result


# --- parser ---


def test_extract_from_fence() -> None:
    text = f"Here is the fix:\n```diff\n{VALID_PATCH}```\nDone."
    result = extract_patch(text)
    assert result is not None
    assert "return" in result


def test_extract_from_bare_header() -> None:
    text = f"Apply this:\n{VALID_PATCH}"
    result = extract_patch(text)
    assert result is not None


def test_extract_returns_none_for_garbage() -> None:
    assert extract_patch("no patch here") is None


def test_extract_returns_none_for_empty_fence() -> None:
    assert extract_patch("```diff\n```") is None


def test_parse_patch_returns_patchset() -> None:
    ps = parse_patch(VALID_PATCH)
    assert len(ps) == 1
    assert ps[0].path == "hello.py"


# --- validator ---


@pytest.mark.asyncio
async def test_validate_calls_apply_check(tmp_path: Path) -> None:
    runner = MockShellRunner([ShellResult("", 0)])
    result = await validate_patch(VALID_PATCH, runner, tmp_path)
    assert result.ok
    assert "--check" in runner.calls[0]


@pytest.mark.asyncio
async def test_validate_returns_error_on_failure(tmp_path: Path) -> None:
    runner = MockShellRunner([ShellResult("error: patch failed", 1)])
    result = await validate_patch(VALID_PATCH, runner, tmp_path)
    assert not result.ok


# --- applier ---


@pytest.mark.asyncio
async def test_apply_patch_command(tmp_path: Path) -> None:
    runner = MockShellRunner([ShellResult("", 0)])
    result = await apply_patch(VALID_PATCH, runner, tmp_path)
    assert result.ok
    assert "apply" in runner.calls[0]
    assert "--check" not in runner.calls[0]


@pytest.mark.asyncio
async def test_rollback_command(tmp_path: Path) -> None:
    runner = MockShellRunner([ShellResult("", 0)])
    await rollback(runner, tmp_path)
    assert runner.calls[0] == ["git", "restore", "."]


# --- test runner ---


def test_parse_passed_only() -> None:
    out = "5 passed in 0.42s"
    r = _parse(ShellResult(out, 0))
    assert r == RunResult(passed=5, failed=0, duration=0.42, output=out, ok=True)


def test_parse_passed_and_failed() -> None:
    out = "3 passed, 2 failed in 1.1s"
    r = _parse(ShellResult(out, 1))
    assert r.passed == 3
    assert r.failed == 2
    assert not r.ok


def test_parse_no_summary_line() -> None:
    out = "ImportError: cannot import name X\n2 failed"
    r = _parse(ShellResult(out, 1))
    assert r.failed == 2
    assert not r.ok


def test_parse_clean_run() -> None:
    out = "no tests ran"
    r = _parse(ShellResult(out, 0))
    assert r.ok
    assert r.failed == 0


@pytest.mark.asyncio
async def test_run_tests_uses_cmd_and_cwd(tmp_path: Path) -> None:
    runner = MockShellRunner([ShellResult("1 passed in 0.1s", 0)])
    result = await run_tests(["pytest", "-x"], runner, tmp_path)
    assert result.ok
    assert runner.calls[0] == ["pytest", "-x"]
