"""Tests for GitHub Release API client."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from github_release_publisher.github_client import GitHubClient


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_session() -> MagicMock:
    """Подменяем requests.Session — ни один запрос не уходит в сеть."""
    with patch.object(requests, "Session", autospec=True) as mock:
        session_instance = mock.return_value
        session_instance.headers = {}
        session_instance.post.return_value = _ok_response({})
        session_instance.get.return_value = _ok_response([])
        yield session_instance


def _ok_response(data):
    r = MagicMock(spec=requests.Response)
    r.ok = True
    r.status_code = 200 if isinstance(data, list) else 201
    r.json.return_value = data
    r.raise_for_status = MagicMock()
    return r


def _error_response(status=422):
    r = MagicMock(spec=requests.Response)
    r.ok = False
    r.status_code = status
    r.raise_for_status.side_effect = requests.HTTPError(
        f"{status} Client Error", response=r
    )
    return r


# ---------------------------------------------------------------------------
# GitHubClient.__init__
# ---------------------------------------------------------------------------

def test_init_with_token() -> None:
    """Токен из аргумента."""
    client = GitHubClient(token="ghp_test")
    assert client.token == "ghp_test"


def test_init_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Токен из переменной окружения."""
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_env_token")
    client = GitHubClient()
    assert client.token == "ghp_env_token"


def test_init_no_token() -> None:
    """Без токена — ошибка."""
    with pytest.raises(ValueError, match="Токен не указан"):
        GitHubClient(token="")


# ---------------------------------------------------------------------------
# create_release
# ---------------------------------------------------------------------------

def test_create_release(mock_session: MagicMock) -> None:
    """Успешное создание релиза."""
    mock_session.post.return_value = _ok_response({
        "id": 1,
        "tag_name": "v1.0.0",
        "upload_url": "https://uploads.github.com/.../assets{?name,label}",
    })

    client = GitHubClient(token="dummy")
    result = client.create_release(repo="owner/repo", tag="v1.0.0", name="v1.0.0", body="Release body")

    mock_session.post.assert_called_once_with(
        "https://api.github.com/repos/owner/repo/releases",
        json={"tag_name": "v1.0.0", "name": "v1.0.0", "body": "Release body"},
    )
    assert result["id"] == 1


def test_create_release_dry_run(mock_session: MagicMock) -> None:
    """dry_run не вызывает API, возвращает данные без id."""
    client = GitHubClient(token="dummy")
    result = client.create_release(
        repo="owner/repo", tag="v1.0.0", name="v1.0.0", body="Test", dry_run=True
    )

    mock_session.post.assert_not_called()
    assert result["dry_run"] is True
    assert result["tag_name"] == "v1.0.0"


def test_create_release_http_error(mock_session: MagicMock) -> None:
    """Ошибка API пробрасывается как HTTPError."""
    mock_session.post.return_value = _error_response(422)

    client = GitHubClient(token="dummy")
    with pytest.raises(requests.HTTPError):
        client.create_release(repo="owner/repo", tag="v1.0.0")


def test_create_release_invalid_repo(mock_session: MagicMock) -> None:
    """Неверный формат репозитория."""
    client = GitHubClient(token="dummy")
    with pytest.raises(ValueError, match="owner/repo"):
        client.create_release(repo="invalid", tag="v1.0.0")


# ---------------------------------------------------------------------------
# upload_asset
# ---------------------------------------------------------------------------

def test_upload_asset(tmp_path: Path, mock_session: MagicMock) -> None:
    """Загрузка бинарного файла как asset."""
    asset_file = tmp_path / "app-linux-amd64"
    asset_file.write_bytes(b"binary content")

    release_data = {
        "id": 1,
        "upload_url": "https://uploads.github.com/repos/owner/repo/releases/1/assets{?name,label}",
    }
    mock_session.post.return_value = _ok_response({
        "id": 101,
        "name": "app-linux-amd64",
        "browser_download_url": "https://github.com/owner/repo/releases/download/v1.0.0/app-linux-amd64",
    })

    client = GitHubClient(token="dummy")
    result = client.upload_asset(release_data, str(asset_file))

    expected_url = (
        "https://uploads.github.com/repos/owner/repo/releases/1/assets"
        "?name=app-linux-amd64"
    )
    mock_session.post.assert_called_once_with(
        expected_url,
        data=b"binary content",
        headers={"Content-Type": "application/octet-stream"},
    )
    assert result["id"] == 101
    assert result["name"] == "app-linux-amd64"


def test_upload_asset_file_not_found(mock_session: MagicMock) -> None:
    """Файл не существует — ошибка FileNotFoundError."""
    release_data = {
        "upload_url": "https://uploads.github.com/.../assets{?name,label}",
    }
    client = GitHubClient(token="dummy")
    with pytest.raises(FileNotFoundError):
        client.upload_asset(release_data, "/nonexistent/file.bin")


def test_upload_asset_http_error(tmp_path: Path, mock_session: MagicMock) -> None:
    """Ошибка при загрузке asset."""
    asset_file = tmp_path / "broken.bin"
    asset_file.write_bytes(b"data")

    release_data = {
        "upload_url": "https://uploads.github.com/repos/owner/repo/releases/1/assets{?name,label}",
    }
    mock_session.post.return_value = _error_response(403)

    client = GitHubClient(token="dummy")
    with pytest.raises(requests.HTTPError):
        client.upload_asset(release_data, str(asset_file))


# ---------------------------------------------------------------------------
# list_releases
# ---------------------------------------------------------------------------

def test_list_releases(mock_session: MagicMock) -> None:
    """Список релизов."""
    mock_session.get.return_value = _ok_response([
        {"id": 1, "tag_name": "v1.0.0", "name": "v1.0.0"},
        {"id": 2, "tag_name": "v2.0.0", "name": "v2.0.0"},
    ])

    client = GitHubClient(token="dummy")
    result = client.list_releases(repo="owner/repo")

    mock_session.get.assert_called_once_with(
        "https://api.github.com/repos/owner/repo/releases"
    )
    assert len(result) == 2
    assert result[0]["tag_name"] == "v1.0.0"


def test_list_releases_empty(mock_session: MagicMock) -> None:
    """Пустой список релизов."""
    mock_session.get.return_value = _ok_response([])

    client = GitHubClient(token="dummy")
    result = client.list_releases(repo="owner/repo")
    assert result == []


def test_list_releases_http_error(mock_session: MagicMock) -> None:
    """Ошибка при получении списка."""
    mock_session.get.return_value = _error_response(404)

    client = GitHubClient(token="dummy")
    with pytest.raises(requests.HTTPError):
        client.list_releases(repo="owner/repo")
