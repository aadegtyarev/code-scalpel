"""Тесты для HTML-парсинга ссылок."""

from link_parser import extract_links, is_valid_url


def test_extract_links_a_href() -> None:
    html = '<a href="https://python.org">Python</a>'
    assert extract_links(html, "https://example.com") == ["https://python.org"]


def test_extract_links_img_src() -> None:
    html = '<img src="https://example.com/logo.png">'
    assert extract_links(html, "https://example.com") == ["https://example.com/logo.png"]


def test_extract_links_relative_to_absolute() -> None:
    html = '<a href="/docs">Docs</a>'
    assert extract_links(html, "https://example.com") == ["https://example.com/docs"]


def test_extract_links_relative_subpath() -> None:
    html = '<a href="page.html">Page</a>'
    assert extract_links(html, "https://example.com/sub/") == ["https://example.com/sub/page.html"]


def test_extract_links_no_links() -> None:
    assert extract_links("<p>No links</p>", "https://example.com") == []


def test_extract_links_multiple() -> None:
    html = '<a href="https://a.com">A</a> <a href="/b">B</a> <img src="https://c.com/img.png">'
    links = extract_links(html, "https://base.com")
    assert links == ["https://a.com", "https://base.com/b", "https://c.com/img.png"]


def test_extract_links_empty_html() -> None:
    assert extract_links("", "https://example.com") == []


def test_is_valid_url_http() -> None:
    assert is_valid_url("https://python.org") is True
    assert is_valid_url("http://example.com") is True


def test_is_valid_url_relative() -> None:
    assert is_valid_url("/path/to/page") is True
    assert is_valid_url("relative/path") is True


def test_is_valid_url_empty() -> None:
    assert is_valid_url("") is False
    assert is_valid_url("   ") is False


def test_is_valid_url_special() -> None:
    assert is_valid_url("mailto:user@example.com") is True
    assert is_valid_url("ftp://files.example.com") is True


def test_is_valid_url_with_query() -> None:
    assert is_valid_url("https://example.com/?q=1&r=2") is True
