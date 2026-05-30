"""Tests for web_search tool — DDG Lite parser and tool dispatch."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_parse_ddg_lite_extracts_results() -> None:
    # DDG Lite uses single-quoted attributes and href before class
    from code_scalpel.tools.web_search import _parse_ddg_lite

    html = """
    <tr><td><a rel="nofollow" href='https://example.com' class='result-link'>TOML spec</a></td></tr>
    <tr><td class='result-snippet'>Use <b>name = "value"</b> syntax in inline tables.</td></tr>
    <tr><td><a rel="nofollow" href='https://other.com' class='result-link'>PEP 518</a></td></tr>
    <tr><td class='result-snippet'>pyproject.toml build system spec.</td></tr>
    """
    result = _parse_ddg_lite(html, max_results=5)

    assert "TOML spec" in result
    assert "PEP 518" in result
    assert 'name = "value"' in result or "name =" in result


def test_parse_ddg_lite_no_results_returns_message() -> None:
    from code_scalpel.tools.web_search import _parse_ddg_lite

    result = _parse_ddg_lite("<html><body></body></html>")
    assert "No results" in result


def test_parse_ddg_lite_strips_html_tags() -> None:
    from code_scalpel.tools.web_search import _parse_ddg_lite

    html = """
    <tr><td><a href='https://x.com' class='result-link'>Title <b>bold</b></a></td></tr>
    <tr><td class='result-snippet'>Snippet with <em>emphasis</em> text.</td></tr>
    """
    result = _parse_ddg_lite(html)

    assert "<b>" not in result
    assert "<em>" not in result
    assert "Title bold" in result
    assert "emphasis" in result


@pytest.mark.asyncio
async def test_web_search_tool_dispatch_unknown_query(tmp_path: Path) -> None:
    """web_search with empty query returns an error ToolResult."""

    from code_scalpel.tools.agent_tools import ToolCall, execute

    call = ToolCall(name="web_search", body='{"query": ""}')
    result = await execute(call, tmp_path)
    assert result.ok is False
    assert "query" in result.output.lower()


def test_top_result_extracts_first_url() -> None:
    from code_scalpel.tools.web_search import _top_result

    html = """
    <tr><td><a href='https://docs.python.org/pyproject' class='result-link'>Python Packaging</a></td></tr>
    <tr><td><a href='https://other.com' class='result-link'>Other</a></td></tr>
    """
    result = _top_result(html)
    assert result is not None
    title, url = result
    assert url == "https://docs.python.org/pyproject"
    assert "Python" in title


def test_top_result_returns_none_when_empty() -> None:
    from code_scalpel.tools.web_search import _top_result

    assert _top_result("<html></html>") is None


def test_query_to_recipe_name() -> None:
    from code_scalpel.agent import _query_to_recipe_name

    assert _query_to_recipe_name("pyproject.toml TOML syntax") == "pyproject-toml-toml-syntax"
    assert _query_to_recipe_name("  ") == "web-recipe"
