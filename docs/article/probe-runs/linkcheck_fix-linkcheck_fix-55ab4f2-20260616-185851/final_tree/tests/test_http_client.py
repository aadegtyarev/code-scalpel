"""Тесты для HTTP-клиента."""

import types

import requests

from http_client import check_link


def _mock_resp(status_code: int) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        status_code=status_code,
        headers={},
        ok=status_code < 400,
        reason="OK" if status_code < 400 else "Error",
    )


def test_check_link_200(monkeypatch) -> None:
    def mock_head(self, *args, **kwargs):
        return _mock_resp(200)
    monkeypatch.setattr(requests.Session, "head", mock_head)
    assert check_link("https://example.com") == 200


def test_check_link_404(monkeypatch) -> None:
    def mock_head(self, *args, **kwargs):
        return _mock_resp(404)
    monkeypatch.setattr(requests.Session, "head", mock_head)
    assert check_link("https://example.com/404") == 404


def test_check_link_fallback_to_get(monkeypatch) -> None:
    call_log = []
    def mock_head(self, *args, **kwargs):
        call_log.append("head")
        return _mock_resp(405)
    def mock_get(self, *args, **kwargs):
        call_log.append("get")
        return _mock_resp(200)
    monkeypatch.setattr(requests.Session, "head", mock_head)
    monkeypatch.setattr(requests.Session, "get", mock_get)
    assert check_link("https://example.com/api") == 200
    assert call_log == ["head", "get"]


def test_check_link_timeout(monkeypatch) -> None:
    def mock_head(self, *args, **kwargs):
        raise requests.exceptions.Timeout("timed out")
    monkeypatch.setattr(requests.Session, "head", mock_head)
    assert check_link("https://example.com/slow") == 0


def test_check_link_connection_error(monkeypatch) -> None:
    def mock_head(self, *args, **kwargs):
        raise requests.exceptions.ConnectionError("connection failed")
    monkeypatch.setattr(requests.Session, "head", mock_head)
    assert check_link("https://nonexistent.example.com") == 0


def test_check_link_with_custom_timeout(monkeypatch) -> None:
    def mock_head(self, *args, **kwargs):
        assert kwargs["timeout"] == 5
        return _mock_resp(200)
    monkeypatch.setattr(requests.Session, "head", mock_head)
    assert check_link("https://example.com", timeout=5) == 200


def test_check_link_500(monkeypatch) -> None:
    def mock_head(self, *args, **kwargs):
        return _mock_resp(500)
    monkeypatch.setattr(requests.Session, "head", mock_head)
    assert check_link("https://example.com/error") == 500
