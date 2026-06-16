"""Тесты для проверки ссылок на доступность."""

from pathlib import Path
import types

import requests

from link_checker import (
    is_http_url,
    is_relative_url,
    check_local_file,
    check_http_url,
)


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


def test_check_local_file_found(tmp_path: Path) -> None:
    md_file = tmp_path / "doc" / "readme.md"
    md_file.parent.mkdir(parents=True)
    md_file.write_text("")
    target = tmp_path / "doc" / "other.md"
    target.write_text("")

    result = check_local_file("./other.md", str(md_file))
    assert result["ok"] is True
    assert "найден" in result["status"]


def test_check_local_file_not_found(tmp_path: Path) -> None:
    md_file = tmp_path / "doc" / "readme.md"
    md_file.parent.mkdir(parents=True)
    md_file.write_text("")

    result = check_local_file("./missing.md", str(md_file))
    assert result["ok"] is False
    assert "не найден" in result["status"]


def _mock_resp(status_code: int) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        status_code=status_code,
        headers={},
        ok=status_code < 400,
        reason="OK" if status_code < 400 else "Error",
    )


def test_check_http_url_success(monkeypatch) -> None:
    """Успешный HEAD-запрос возвращает ok=True."""
    def mock_head(self, *args, **kwargs):
        return _mock_resp(200)

    monkeypatch.setattr(requests.Session, "head", mock_head)
    result = check_http_url("https://example.com")
    assert result["ok"] is True
    assert "200" in result["status"]


def test_check_http_url_not_found(monkeypatch) -> None:
    """404 возвращает ok=False."""
    def mock_head(self, *args, **kwargs):
        return _mock_resp(404)

    monkeypatch.setattr(requests.Session, "head", mock_head)
    result = check_http_url("https://example.com/404")
    assert result["ok"] is False
    assert "404" in result["status"]


def test_check_http_url_fallback_to_get(monkeypatch) -> None:
    """Если HEAD возвращает 405, делается GET."""
    call_log = []

    def mock_head(self, *args, **kwargs):
        call_log.append("head")
        return _mock_resp(405)

    def mock_get(self, *args, **kwargs):
        call_log.append("get")
        return _mock_resp(200)

    monkeypatch.setattr(requests.Session, "head", mock_head)
    monkeypatch.setattr(requests.Session, "get", mock_get)

    result = check_http_url("https://example.com/api")
    assert result["ok"] is True
    assert call_log == ["head", "get"]


def test_check_link_http(monkeypatch) -> None:
    from link_checker import check_link

    def mock_head(self, url, *args, **kwargs):
        return _mock_resp(200)

    monkeypatch.setattr(requests.Session, "head", mock_head)
    result = check_link("https://python.org", "test.md")
    assert result["ok"] is True


def test_check_link_local(tmp_path: Path) -> None:
    from link_checker import check_link
    md_file = tmp_path / "readme.md"
    target = tmp_path / "other.md"
    target.write_text("")
    md_file.write_text("")

    result = check_link("./other.md", str(md_file))
    assert result["ok"] is True
    assert "найден" in result["status"]


def test_check_link_non_http() -> None:
    from link_checker import check_link
    result = check_link("mailto:user@example.com", "test.md")
    assert result["ok"] is True
    assert "пропущено" in result["status"]
