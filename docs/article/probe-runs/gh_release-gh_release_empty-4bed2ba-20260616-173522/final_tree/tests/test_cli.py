"""Tests for the CLI (publish / list commands)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from github_release_publisher.cli import cli


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------

@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def sample_changelog(tmp_path: Path) -> Path:
    """CHANGELOG.md с одной версией."""
    path = tmp_path / "CHANGELOG.md"
    path.write_text(
        "# Changelog\n"
        "\n"
        "## [1.2.0] - 2025-05-15\n"
        "\n"
        "### Added\n"
        "- Feature A\n"
        "- Feature B\n"
        "\n"
        "### Fixed\n"
        "- Bugfix C\n"
    )
    return path


@pytest.fixture
def sample_asset(tmp_path: Path) -> Path:
    path = tmp_path / "app.bin"
    path.write_bytes(b"binary content")
    return path


@pytest.fixture(autouse=True)
def mock_github_client():
    """Подменяем GitHubClient во всех тестах — ни одного реального запроса."""
    with patch(
        "github_release_publisher.cli.GitHubClient", autospec=True
    ) as mock:
        instance = mock.return_value
        instance.create_release.return_value = {
            "id": 1,
            "tag_name": "v1.2.0",
            "html_url": "https://github.com/owner/repo/releases/tag/v1.2.0",
            "upload_url": "https://uploads.github.com/.../assets{?name,label}",
        }
        instance.list_releases.return_value = [
            {
                "tag_name": "v1.2.0",
                "name": "v1.2.0",
                "published_at": "2025-05-15T10:00:00Z",
                "draft": False,
                "prerelease": False,
            },
        ]
        instance.upload_asset.return_value = {
            "id": 101,
            "name": "app.bin",
            "browser_download_url": (
                "https://github.com/owner/repo/releases/download/"
                "v1.2.0/app.bin"
            ),
        }
        yield mock


# ---------------------------------------------------------------------------
# publish
# ---------------------------------------------------------------------------

def test_publish_happy_path(
    runner: CliRunner,
    sample_changelog: Path,
    sample_asset: Path,
    mock_github_client: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
):
    """publish с changelog, assets, токеном — успех."""
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_dummy")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")

    result = runner.invoke(cli, [
        "publish",
        "--changelog", str(sample_changelog),
        "--assets", str(sample_asset),
    ])

    assert result.exit_code == 0, result.output

    mock_github_client.return_value.create_release.assert_called_once_with(
        repo="owner/repo",
        tag="v1.2.0",
        name="v1.2.0",
        body="### Added\n- Feature A\n- Feature B\n\n### Fixed\n- Bugfix C",
    )

    mock_github_client.return_value.upload_asset.assert_called_once()
    assert "✅" in result.output


def test_publish_dry_run(
    runner: CliRunner,
    sample_changelog: Path,
    sample_asset: Path,
    mock_github_client: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
):
    """dry-run не вызывает API."""
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_dummy")

    result = runner.invoke(cli, [
        "publish",
        "--repo", "owner/repo",
        "--changelog", str(sample_changelog),
        "--assets", str(sample_asset),
        "--dry-run",
    ])

    assert result.exit_code == 0, result.output
    assert "[DRY RUN]" in result.output

    mock_github_client.return_value.create_release.assert_not_called()
    mock_github_client.return_value.upload_asset.assert_not_called()


def test_publish_no_version_in_changelog(
    runner: CliRunner,
    tmp_path: Path,
    mock_github_client: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
):
    """Changelog без версий — ошибка."""
    empty = tmp_path / "CHANGELOG.md"
    empty.write_text("# Changelog\n\nNothing here.\n")

    monkeypatch.setenv("GITHUB_TOKEN", "ghp_dummy")

    result = runner.invoke(cli, [
        "publish",
        "--repo", "owner/repo",
        "--changelog", str(empty),
    ])

    assert result.exit_code == 1
    assert "Не найдено" in result.output


def test_publish_no_repo(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Без --repo и без GITHUB_REPOSITORY — ошибка."""
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    changelog = tmp_path / "ch.md"
    changelog.write_text("## [1.0.0] - 2025-01-01\n\nRelease\n")

    result = runner.invoke(cli, [
        "publish",
        "--changelog", str(changelog),
    ])

    assert result.exit_code == 2
    assert "GITHUB_REPOSITORY" in result.output


def test_publish_no_token(
    runner: CliRunner,
    sample_changelog: Path,
    mock_github_client: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
):
    """Без токена — ошибка."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    mock_github_client.side_effect = ValueError(
        "Токен не указан. Передайте token= или установите GITHUB_TOKEN"
    )

    result = runner.invoke(cli, [
        "publish",
        "--repo", "owner/repo",
        "--changelog", str(sample_changelog),
    ])

    assert result.exit_code == 1
    assert "Токен не указан" in result.output


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

def test_list_happy_path(
    runner: CliRunner,
    mock_github_client: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
):
    """list с repo из аргумента."""
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_dummy")

    result = runner.invoke(cli, ["list", "--repo", "owner/repo"])

    assert result.exit_code == 0, result.output
    assert "v1.2.0" in result.output
    mock_github_client.return_value.list_releases.assert_called_once_with(
        "owner/repo"
    )


def test_list_from_env(
    runner: CliRunner,
    mock_github_client: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
):
    """list c repo из GITHUB_REPOSITORY."""
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_dummy")
    monkeypatch.setenv("GITHUB_REPOSITORY", "org/my-repo")
    mock_github_client.return_value.list_releases.return_value = [
        {"tag_name": "v0.1.0", "name": "v0.1.0", "published_at": "2024-01-01T00:00:00Z"},
    ]

    result = runner.invoke(cli, ["list"])

    assert result.exit_code == 0
    assert "v0.1.0" in result.output
    mock_github_client.return_value.list_releases.assert_called_once_with(
        "org/my-repo"
    )


def test_list_empty(
    runner: CliRunner,
    mock_github_client: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
):
    """Релизов нет — '(пусто)'."""
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_dummy")
    mock_github_client.return_value.list_releases.return_value = []

    result = runner.invoke(cli, ["list", "--repo", "owner/repo"])

    assert result.exit_code == 0
    assert "пусто" in result.output


def test_list_no_repo(runner: CliRunner, monkeypatch: pytest.MonkeyPatch):
    """Без --repo и без GITHUB_REPOSITORY — ошибка."""
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)

    result = runner.invoke(cli, ["list"])

    assert result.exit_code == 2
    assert "GITHUB_REPOSITORY" in result.output
