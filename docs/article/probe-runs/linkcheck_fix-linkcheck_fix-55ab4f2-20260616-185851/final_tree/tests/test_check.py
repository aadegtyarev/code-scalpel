"""Тесты для проверки ссылок — импорты из правильных модулей."""

from link_parser import is_http_url, is_relative_url


def test_is_http_url_positive() -> None:
    assert is_http_url("https://python.org") is True
    assert is_http_url("http://example.com") is True


def test_is_http_url_negative() -> None:
    assert is_http_url("./local.md") is False
    assert is_http_url("/absolute/path") is False
    assert is_http_url("mailto:user@example.com") is False
    assert is_http_url("ftp://files.example.com") is False


def test_is_relative_url() -> None:
    assert is_relative_url("./relative.md") is True
    assert is_relative_url("../other.md") is True
    assert is_relative_url("docs/guide.md") is True
    assert is_relative_url("") is False
    assert is_relative_url("https://example.com") is False
    assert is_relative_url("/absolute/path") is True
